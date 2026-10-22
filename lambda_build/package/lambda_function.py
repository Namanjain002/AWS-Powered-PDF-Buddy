import os
import re
import urllib.parse
import boto3
import psycopg
import pymupdf as fitz
from pgvector.psycopg import register_vector
from openai import OpenAI

s3 = boto3.client("s3")
client = OpenAI()  # reads OPENAI_API_KEY from the environment


def clean(text):
    text = re.sub(r'(\s*\.){4,}', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def chunk_text(text, size=1000, overlap=150):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks

def embed(texts):
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in resp.data]


def ingest(conn, user_id, key, local_path):
    filename = os.path.basename(key)

    # re-uploading the same file replaces the old copy (chunks go too, via ON DELETE CASCADE)
    conn.execute("DELETE FROM documents WHERE s3_key = %s AND user_id = %s", (key, user_id))
    doc_id = conn.execute(
        "INSERT INTO documents (user_id, s3_key, filename, status) "
        "VALUES (%s, %s, %s, 'processing') RETURNING id",
        (user_id, key, filename),
    ).fetchone()[0]
    conn.commit()  # commit now so the 'processing' status is visible right away

    try:
        rows = []
        idx = 0
        with fitz.open(local_path) as pdf:
            for page_num, page in enumerate(pdf, start=1):
                text = clean(page.get_text())
                for c in chunk_text(text):
                    if len(c.strip()) > 80:
                        rows.append((page_num, idx, c))
                        idx += 1

        for i in range(0, len(rows), 64):
            batch = rows[i:i + 64]
            vectors = embed([r[2] for r in batch])
            for (page_num, chunk_idx, content), vec in zip(batch, vectors):
                conn.execute(
                    "INSERT INTO chunks "
                    "(document_id, user_id, page_number, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (doc_id, user_id, page_num, chunk_idx, content, vec),
                )

        conn.execute("UPDATE documents SET status='ready' WHERE id=%s", (doc_id,))
        conn.commit()
        print(f"Done: {len(rows)} chunks from {key}")

    except Exception as e:
        conn.rollback()  # throw away any half-inserted chunks
        conn.execute("UPDATE documents SET status='failed' WHERE id=%s", (doc_id,))
        conn.commit()
        print(f"FAILED {key}: {e}")

def lambda_handler(event, context):
    # TODO implement
    conn = psycopg.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        dbname="postgres",
        sslmode = "require",
    )
    register_vector(conn)

    try:
        for rec in event["Records"]:
            bucket = rec["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])

            parts = key.split("/")  # ["users", "<user_id>", "notes", "file.pdf"]
            if len(parts) < 3 or parts[0] != "users" or not key.lower().endswith(".pdf"):
                continue
            user_id = parts[1]

            local_path = "/tmp/" + os.path.basename(key)
            s3.download_file(bucket, key, local_path)
            ingest(conn, user_id, key, local_path)
            os.remove(local_path)
    finally:
        conn.close()

