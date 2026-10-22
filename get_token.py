import boto3, getpass
from botocore import UNSIGNED
from botocore.config import Config

REGION = "REGION OF COGNITO"            # your Cognito region
CLIENT_ID = "YOUR CLIENT ID"

# UNSIGNED = no AWS credentials needed
cog = boto3.client("cognito-idp", region_name=REGION, config=Config(signature_version=UNSIGNED))

email = input("email: ")
password = getpass.getpass("password: ")

resp = cog.initiate_auth(
    ClientId=CLIENT_ID,
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters={"USERNAME": email, "PASSWORD": password},
)

# if the user was created by you in the console, Cognito may force a new password first
if resp.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
    new_pw = getpass.getpass("choose a new permanent password: ")
    resp = cog.respond_to_auth_challenge(
        ClientId=CLIENT_ID,
        ChallengeName="NEW_PASSWORD_REQUIRED",
        Session=resp["Session"],
        ChallengeResponses={"USERNAME": email, "NEW_PASSWORD": new_pw},
    )

tokens = resp["AuthenticationResult"]
print("\nID TOKEN:\n", tokens["IdToken"])