#!/usr/bin/env python3
from pyrogram import Client

app = Client('maxvpn_session', api_id=34168798, api_hash='ccac9b2ce48f8fffc08ea067f69bf417')

app.start()
session_string = app.export_session_string()
app.stop()

# Save to file
with open('session_string.txt', 'w') as f:
    f.write(session_string)

print("Session string saved to session_string.txt")
print("Copy the content of this file to config.json -> pyrogram_session_string")
