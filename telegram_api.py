import asyncio
import logging
from telethon import TelegramClient, functions, types, errors
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat, InputPeerChannel, InputPeerUser, InputUser, UserStatusRecently, UserStatusOnline
from config import Config

logger = logging.getLogger(__name__)

class TelegramAPI:
    def __init__(self, api_id=None, api_hash=None):
        self.api_id = api_id or Config.API_ID
        self.api_hash = api_hash or Config.API_HASH

    def create_client(self, session_string=None):
        """Create telethon TelegramClient instance"""
        session = StringSession(session_string) if session_string else StringSession()
        return TelegramClient(session, self.api_id, self.api_hash)

    async def send_code_request(self, phone_number):
        """Send OTP code to phone number for login"""
        client = self.create_client()
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone_number)
            phone_code_hash = sent_code.phone_code_hash
            session_str = client.session.save()
            await client.disconnect()
            return {
                'status': 'success',
                'phone_code_hash': phone_code_hash,
                'session_string': session_str
            }
        except Exception as e:
            await client.disconnect()
            raise e

    async def sign_in_with_code(self, phone_number, phone_code_hash, code, temp_session_string):
        """Complete sign in using verification code or return 2FA needed state"""
        client = self.create_client(temp_session_string)
        await client.connect()
        try:
            user = await client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
            final_session = client.session.save()
            await client.disconnect()
            return {
                'status': 'success',
                'session_string': final_session,
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name
            }
        except errors.SessionPasswordNeededError:
            current_session = client.session.save()
            await client.disconnect()
            return {
                'status': 'password_needed',
                'message': '2FA Password Required',
                'session_string': current_session
            }
        except Exception as e:
            await client.disconnect()
            raise e

    async def sign_in_with_password(self, password, temp_session_string):
        """Sign in with 2FA password"""
        client = self.create_client(temp_session_string)
        await client.connect()
        try:
            user = await client.sign_in(password=password)
            final_session = client.session.save()
            await client.disconnect()
            return {
                'status': 'success',
                'session_string': final_session,
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name
            }
        except Exception as e:
            await client.disconnect()
            raise e

    async def get_entity_from_link(self, session_string, group_link):
        """Resolve entity from public link, username, or invite link"""
        client = self.create_client(session_string)
        await client.connect()
        try:
            link = group_link.strip()
            if 'joinchat/' in link or '+' in link:
                hash_val = link.split('+')[-1].split('/')[-1]
                try:
                    updates = await client(functions.messages.ImportChatInviteRequest(hash_val))
                    entity = updates.chats[0]
                except errors.UserAlreadyParticipantError:
                    entity = await client.get_entity(link)
            else:
                entity = await client.get_entity(link)
                
            input_entity = await client.get_input_entity(entity)
            await client.disconnect()
            return {
                'entity': entity,
                'input_entity': input_entity,
                'title': getattr(entity, 'title', 'Group'),
                'id': entity.id
            }
        except Exception as e:
            await client.disconnect()
            logger.error(f"Error fetching entity {group_link}: {e}")
            raise e

    async def scrape_members_advanced(self, session_string, target_entity, limit=500, filter_keywords=None, exclude_keywords=None):
        """Scrape members from target channel/group with advanced filtering"""
        client = self.create_client(session_string)
        await client.connect()
        
        filter_keywords = [k.lower() for k in (filter_keywords or [])]
        exclude_keywords = [k.lower() for k in (exclude_keywords or [])]
        
        scraped_members = []
        filtered_out = 0
        
        try:
            all_participants = await client.get_participants(target_entity, limit=limit)
            
            for user in all_participants:
                if not isinstance(user, User):
                    continue
                
                if user.bot or user.deleted:
                    filtered_out += 1
                    continue
                
                username = user.username or ''
                first_name = user.first_name or ''
                last_name = user.last_name or ''
                full_text = f"{username} {first_name} {last_name}".lower()
                
                if filter_keywords and not any(k in full_text for k in filter_keywords):
                    filtered_out += 1
                    continue
                
                if exclude_keywords and any(k in full_text for k in exclude_keywords):
                    filtered_out += 1
                    continue
                
                scraped_members.append({
                    'id': user.id,
                    'access_hash': user.access_hash,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'phone': user.phone
                })
                
            await client.disconnect()
            return scraped_members, filtered_out
        except Exception as e:
            await client.disconnect()
            logger.error(f"Scraping error: {e}")
            raise e

    async def add_members_with_delay(self, session_string, target_group_entity, members_list, delay=3, progress_callback=None):
        """Add members to target group with accurate verification and error handling"""
        client = self.create_client(session_string)
        await client.connect()
        
        added_count = 0
        failed_count = 0
        failed_members = []
        
        try:
            target_input = await client.get_input_entity(target_group_entity)
            
            for index, member in enumerate(members_list):
                try:
                    # Construct InputUser directly using scraped ID and access hash
                    if member.get('access_hash'):
                        user_to_add = InputUser(member['id'], member['access_hash'])
                    else:
                        user_to_add = await client.get_input_entity(member['id'])
                    
                    if isinstance(target_input, InputPeerChannel):
                        res = await client(functions.channels.InviteToChannelRequest(
                            channel=target_input,
                            users=[user_to_add]
                        ))
                        # Verify if Telegram actually added the user
                        actual_users = getattr(res, 'users', [])
                        if actual_users and len(actual_users) > 0:
                            added_count += 1
                            logger.info(f"[{index+1}/{len(members_list)}] Truly added member {member.get('username') or member.get('id')}")
                        else:
                            failed_count += 1
                            failed_members.append({'member': member, 'reason': 'Silently restricted by Telegram privacy'})
                            logger.warning(f"[{index+1}/{len(members_list)}] Telegram skipped adding {member.get('id')}")
                    else:
                        await client(functions.messages.AddChatUserRequest(
                            chat_id=target_group_entity.id,
                            user_id=user_to_add,
                            fwd_limit=100
                        ))
                        added_count += 1
                        logger.info(f"[{index+1}/{len(members_list)}] Added chat user {member.get('username') or member.get('id')}")
                    
                except errors.UserPrivacyRestrictedError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Privacy settings restricted'})
                    logger.warning(f"Privacy restricted for member {member.get('id')}")
                except errors.UserNotMutualContactError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Requires mutual contact'})
                except errors.UserChannelsTooMuchError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'User in too many channels'})
                except errors.UserAlreadyParticipantError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Already in target group'})
                except errors.PeerFloodError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Account hit daily adding limit (PeerFloodError)'})
                    logger.warning(f"PeerFloodError! Session account hit Telegram daily adding limit.")
                    if progress_callback:
                        await progress_callback(index + 1, len(members_list), added_count, failed_count)
                    break
                except errors.FloodWaitError as e:
                    logger.warning(f"Flood wait required for {e.seconds} seconds.")
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': f'FloodWait {e.seconds}s'})
                    if progress_callback:
                        await progress_callback(index + 1, len(members_list), added_count, failed_count)
                    await asyncio.sleep(min(e.seconds, 60))
                    break
                except Exception as e:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': str(e)})
                    logger.error(f"Error adding member {member.get('id')}: {e}")
                
                if progress_callback:
                    await progress_callback(index + 1, len(members_list), added_count, failed_count)
                
                await asyncio.sleep(delay)
                
            await client.disconnect()
            return added_count, failed_count, failed_members
        except Exception as e:
            await client.disconnect()
            logger.error(f"Error in add_members_with_delay: {e}")
            raise e
