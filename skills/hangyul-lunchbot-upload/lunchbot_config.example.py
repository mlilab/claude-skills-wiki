"""Local lunchbot settings - copy to lunchbot_config.py and fill in.

    cp lunchbot_config.example.py lunchbot_config.py
    chmod 600 lunchbot_config.py

lunchbot_config.py is git-ignored. Environment variables with the same
names take precedence over the values in this file.
"""

# Slack app "Bot User OAuth Token" (starts with xoxb-)
SLACK_BOT_TOKEN = "xoxb-replace-with-your-token"

# Channel the bot posts to (channel details -> channel ID, usually starts with C)
SLACK_CHANNEL_ID = "C_REPLACE_WITH_CHANNEL_ID"

# Google Sheet ID: docs.google.com/spreadsheets/d/<THIS PART>/edit
SHEET_ID = "replace-with-your-spreadsheet-id"

# Account shown in the weekly settlement reminder and the sheet instructions
SETTLE_ACCOUNT = "은행 000-000-000000 예금주"

# Friday lunch on/off (default True: Mon-Fri, False: Mon-Thu)
# INCLUDE_FRIDAY = True
