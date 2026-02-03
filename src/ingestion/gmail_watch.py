import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
TOPIC_NAME = "projects/super-home-automation/topics/gmail-incoming-orders"

def setup_watch(service=None):
    if not service:
        creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists('credentials.json'):
                    print("Error: credentials.json not found.")
                    return

                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        service = build('gmail', 'v1', credentials=creds)

    request = {
        'labelIds': ['INBOX'],
        'topicName': TOPIC_NAME
    }
    
    response = service.users().watch(userId='me', body=request).execute()
    print(f"Watch successfully set up! Response: {response}")
    print(f"Gmail will now notify: {TOPIC_NAME}")
    return response

if __name__ == '__main__':
    setup_watch()
