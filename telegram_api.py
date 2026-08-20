import asyncio
import logging
from telethon import TelegramClient, functions, types, errors
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat, InputPeerChannel, InputPeerUser, UserStatusRecently, UserStatusOnline
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
        """Complete sign in using verification code"""
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
            await client.disconnect()
            return {'status': 'password_needed', 'message': '2FA Password Required'}
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
            # Fetch members
            all_participants = await client.get_participants(target_entity, limit=limit)
            
            for user in all_participants:
                if not isinstance(user, User):
                    continue
                
                # Exclude bots and deleted accounts
                if user.bot or user.deleted:
                    filtered_out += 1
                    continue
                
                username = user.username or ''
                first_name = user.first_name or ''
                last_name = user.last_name or ''
                full_text = f"{username} {first_name} {last_name}".lower()
                
                # Apply filter keywords
                if filter_keywords and not any(k in full_text for k in filter_keywords):
                    filtered_out += 1
                    continue
                
                # Apply exclude keywords
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
        """Add members to target group with delay and error handling"""
        client = self.create_client(session_string)
        await client.connect()
        
        added_count = 0
        failed_count = 0
        failed_members = []
        
        try:
            target_input = await client.get_input_entity(target_group_entity)
            
            for index, member in enumerate(members_list):
                try:
                    user_to_add = await client.get_input_entity(member['id'])
                    
                    # Add member depending on entity type
                    if isinstance(target_input, InputPeerChannel):
                        await client(functions.channels.InviteToChannelRequest(
                            channel=target_input,
                            users=[user_to_add]
                        ))
                    else:
                        await client(functions.messages.AddChatUserRequest(
                            chat_id=target_group_entity.id,
                            user_id=user_to_add,
                            fwd_limit=100
                        ))
                    
                    added_count += 1
                    logger.info(f"Successfully added member {member.get('username') or member.get('id')}")
                    
                except errors.UserPrivacyRestrictedError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Privacy settings restricted'})
                    logger.warning(f"User {member.get('id')} has privacy restrictions.")
                except errors.UserChannelsTooMuchError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'User in too many channels'})
                except errors.UserAlreadyParticipantError:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': 'Already in target group'})
                except errors.FloodWaitError as e:
                    logger.warning(f"Flood wait required for {e.seconds} seconds.")
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': f'FloodWait {e.seconds}s'})
                    await asyncio.sleep(min(e.seconds, 60))  # sleep max 60 seconds or break
                    break
                except Exception as e:
                    failed_count += 1
                    failed_members.append({'member': member, 'reason': str(e)})
                    logger.error(f"Error adding member {member.get('id')}: {e}")
                
                if progress_callback:
                    await progress_callback(index + 1, len(members_list), added_count, failed_count)
                
                # Delay between additions
                await asyncio.sleep(delay)
                
            await client.disconnect()
            return added_count, failed_count, failed_members
        except Exception as e:
            await client.disconnect()
            logger.error(f"Error in add_members_with_delay: {e}")
            raise e
