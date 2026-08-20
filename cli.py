import asyncio
import os
import sys
import json
from datetime import datetime
from telethon import TelegramClient, functions, types, errors
from telethon.sessions import StringSession

BANNER = """
=====================================================
  Telegram Member Adder CLI v2.0
  Power-Packed Telegram Group Scraper & Auto Adder
=====================================================
"""

async def login_session(api_id, api_hash):
    """Interactively login to Telegram and return session string"""
    print("\n--- Telegram Phone Login ---")
    phone = input("Enter your phone number (with country code, e.g. +91XXXXXXXXXX): ").strip()
    
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        try:
            sent_code = await client.send_code_request(phone)
            code = input("Enter the OTP code received on Telegram: ").strip()
            try:
                await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
            except errors.SessionPasswordNeededError:
                pw = input("Enter your 2FA Password: ").strip()
                await client.sign_in(password=pw)
        except Exception as e:
            print(f"[!] Login failed: {e}")
            await client.disconnect()
            return None
            
    session_str = client.session.save()
    user = await client.get_me()
    print(f"[+] Successfully logged in as {user.first_name} (@{user.username or user.id})")
    await client.disconnect()
    return session_str

async def scrape_members(client, group_link, max_members=500):
    """Scrape members from group link"""
    print(f"\n[*] Fetching group entity: {group_link}...")
    try:
        if 'joinchat/' in group_link or '+' in group_link:
            hash_val = group_link.split('+')[-1].split('/')[-1]
            try:
                updates = await client(functions.messages.ImportChatInviteRequest(hash_val))
                entity = updates.chats[0]
            except errors.UserAlreadyParticipantError:
                entity = await client.get_entity(group_link)
        else:
            entity = await client.get_entity(group_link)
            
        print(f"[+] Target Group: {getattr(entity, 'title', 'Group')}")
        print(f"[*] Scraping up to {max_members} members...")
        
        participants = await client.get_participants(entity, limit=max_members)
        members = []
        for user in participants:
            if isinstance(user, types.User) and not user.bot and not user.deleted:
                members.append({
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'access_hash': user.access_hash
                })
        print(f"[+] Successfully scraped {len(members)} active members.")
        return entity, members
    except Exception as e:
        print(f"[!] Error scraping members: {e}")
        return None, []

async def add_members(client, target_group_entity, members, delay=3):
    """Add scraped members to target group"""
    print(f"\n[*] Starting to add {len(members)} members with {delay}s delay...")
    added = 0
    failed = 0
    
    target_input = await client.get_input_entity(target_group_entity)
    
    for i, m in enumerate(members, 1):
        username_str = f"@{m['username']}" if m['username'] else f"ID: {m['id']}"
        try:
            user_input = await client.get_input_entity(m['id'])
            if isinstance(target_input, types.InputPeerChannel):
                await client(functions.channels.InviteToChannelRequest(
                    channel=target_input,
                    users=[user_input]
                ))
            else:
                await client(functions.messages.AddChatUserRequest(
                    chat_id=target_group_entity.id,
                    user_id=user_input,
                    fwd_limit=100
                ))
            added += 1
            print(f"[{i}/{len(members)}] [+] Added {username_str}")
        except errors.UserPrivacyRestrictedError:
            failed += 1
            print(f"[{i}/{len(members)}] [-] Privacy Restricted: {username_str}")
        except errors.UserAlreadyParticipantError:
            failed += 1
            print(f"[{i}/{len(members)}] [-] Already in group: {username_str}")
        except errors.FloodWaitError as e:
            print(f"[!] Flood Wait Error! Must wait {e.seconds} seconds.")
            break
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(members)}] [-] Failed {username_str}: {e}")
            
        await asyncio.sleep(delay)
        
    print(f"\n[=] Finished. Total Added: {added}, Total Failed: {failed}")

async def main():
    print(BANNER)
    api_id_str = input("Enter Telegram API_ID: ").strip()
    api_hash = input("Enter Telegram API_HASH: ").strip()
    
    if not api_id_str.isdigit() or not api_hash:
        print("[!] Invalid API_ID or API_HASH. Please obtain them from https://my.telegram.org")
        return
        
    api_id = int(api_id_str)
    session_str = None
    
    while True:
        print("\n--- MENU ---")
        print("1. Login & Save Telegram Session")
        print("2. Scrape & Add Members Automatically")
        print("3. Export Scraped Members to JSON")
        print("4. Exit")
        
        choice = input("Select an option (1-4): ").strip()
        
        if choice == '1':
            session_str = await login_session(api_id, api_hash)
            if session_str:
                with open('session.txt', 'w') as f:
                    f.write(session_str)
                print("[+] Session saved to session.txt")
                
        elif choice == '2':
            if not session_str:
                if os.path.exists('session.txt'):
                    with open('session.txt', 'r') as f:
                        session_str = f.read().strip()
                else:
                    session_str = await login_session(api_id, api_hash)
                    
            if not session_str:
                print("[!] Session is required to continue.")
                continue
                
            source_link = input("Enter Source Group Link / Username: ").strip()
            target_link = input("Enter Target Group Link / Username: ").strip()
            max_m = int(input("Max members to scrape [default 500]: ").strip() or "500")
            delay = int(input("Delay between additions in seconds [default 3]: ").strip() or "3")
            
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            
            _, members = await scrape_members(client, source_link, max_m)
            if members:
                target_entity, _ = await scrape_members(client, target_link, limit=1)
                if target_entity:
                    await add_members(client, target_entity, members, delay=delay)
            await client.disconnect()
            
        elif choice == '3':
            if not session_str and os.path.exists('session.txt'):
                with open('session.txt', 'r') as f:
                    session_str = f.read().strip()
            if not session_str:
                print("[!] Login required.")
                continue
            source_link = input("Enter Source Group Link: ").strip()
            max_m = int(input("Max members [500]: ").strip() or "500")
            
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            _, members = await scrape_members(client, source_link, max_m)
            if members:
                filename = f"members_{int(datetime.now().timestamp())}.json"
                with open(filename, 'w') as f:
                    json.dump(members, f, indent=2)
                print(f"[+] Saved scraped members to {filename}")
            await client.disconnect()
            
        elif choice == '4':
            print("Exiting. Goodbye!")
            sys.exit(0)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
