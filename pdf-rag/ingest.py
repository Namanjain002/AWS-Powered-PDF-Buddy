import os,sys
import pymupdf as fitz
import psycopg
import re
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from openai import OpenAI

load_dotenv()

client = OpenAI()
conn = psycopg.connect(
    host = os.environ["DB_HOST"],
    user = os.environ["DB_USER"],
    password = os.environ["DB_PASS"],
    dbname = "postgres",
    sslmode = "require",
)

register_vector(conn)

USER_ID = "Test-user-1"


def clean(text):
    text = re.sub(r'(\s*\.){4,}', ' ', text)   # collapse dot
    text = re.sub(r'\s+', ' ', text)           # normalize whitespace
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

def ingest(path):
    filename = os.path.basename(path)
    doc_id = conn.execute(
        "INSERT INTO documents (user_id, s3_key, filename, status) "
        "VALUES (%s, %s, %s, 'processing') RETURNING id",
        (USER_ID, path, filename),
    ).fetchone()[0]

    rows = []  # (page_number, chunk_index, text)
    idx = 0
    for page_num, page in enumerate(fitz.open(path), start=1):
        text = clean(page.get_text())
        for c in chunk_text(text):
            if len(c.strip()) > 80:   # skip tiny leftovers
                rows.append((page_num, idx, c))
                idx += 1

    for i in range(0, len(rows), 64):  # embed in batches of 64
        batch = rows[i:i + 64]
        vectors = embed([r[2] for r in batch])
        for (page_num, chunk_idx, content), vec in zip(batch, vectors):
            conn.execute(
                "INSERT INTO chunks "
                "(document_id, user_id, page_number, chunk_index, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (doc_id, USER_ID, page_num, chunk_idx, content, vec),
            )

    conn.execute("UPDATE documents SET status='ready' WHERE id=%s", (doc_id,))
    conn.commit()
    print(f"Done: {len(rows)} chunks from {filename}")


def search(query, k=5):
    qvec = embed([query])[0]
    return conn.execute(
        "SELECT page_number, content, embedding <=> %s::vector AS dist "
        "FROM chunks WHERE user_id = %s "
        "ORDER BY embedding <=> %s::vector LIMIT %s",
        (qvec, USER_ID, qvec, k),
    ).fetchall()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:\n  python ingest.py ingest <pdf_path>\n  python ingest.py search \"your question\"")
        sys.exit(1)

    if sys.argv[1] == "ingest":
        ingest(sys.argv[2])
    else:
        for page, content, dist in search(sys.argv[2]):
            print(f"\n--- page {page} (distance {dist:.3f}) ---")
            print(content[:300])