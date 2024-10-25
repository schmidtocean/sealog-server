import sys
import logging
import requests
from collections import defaultdict
from datetime import datetime
import atexit

class PooledSlackHandler(logging.Handler):
    """Custom logging handler that pools messages and sends them as a single digest"""
    
    def __init__(self, webhook_url, minimum_level='WARNING', max_retries=3):
        super().__init__()
        self.webhook_url = webhook_url
        self.max_retries = max_retries
        self.setLevel(getattr(logging, minimum_level))
        
        # Initialize message pools for different log levels
        self.message_pools = defaultdict(list)
        
        # Register the send_digest method to run at exit
        atexit.register(self.send_digest)
        
    def emit(self, record):
        """Store the log record in the appropriate pool"""
        try:
            msg = self.format(record)
            self.message_pools[record.levelno].append({
                'message': msg,
                'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                'logger': record.name
            })
        except Exception as e:
            print(f"Error pooling message: {str(e)}", file=sys.stderr)

    def _get_level_name_and_color(self, level):
        """Get Slack formatting for different log levels"""
        if level >= logging.ERROR:
            return "🚨 *Errors*", "#FF0000"
        elif level >= logging.WARNING:
            return "⚠️ *Warnings*", "#FFA500"
        elif level >= logging.INFO:
            return "ℹ️ *Info*", "#36A64F"
        return "🔍 *Debug*", "#999999"

    def send_digest(self):
        """Send all pooled messages as a single digest"""
        if not any(self.message_pools.values()):
            return  # No messages to send
            
        try:
            # Build the message blocks
            blocks = [{
                'type': 'header',
                'text': {
                    'type': 'plain_text',
                    'text': f'Sealog Export Summary Report'
                }
            }]
            
            # Add divider after header
            blocks.append({'type': 'divider'})
            
            # Process each level of messages
            for level in sorted(self.message_pools.keys(), reverse=True):
                messages = self.message_pools[level]
                if not messages:
                    continue
                    
                level_name, color = self._get_level_name_and_color(level)
                
                # Add section for this level
                blocks.append({
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': f"\n{level_name}"
                    }
                })
                
                # Add messages for this level
                message_text = ""
                for msg in messages:
                    message_text += f"• {msg['timestamp']} - {msg['message']}\n"
                
                blocks.append({
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': message_text
                    }
                })
                
                blocks.append({'type': 'divider'})
            
            # Create the payload
            payload = {
                'blocks': blocks,
                'attachments': [{
                    'color': self._get_level_name_and_color(max(self.message_pools.keys()))[1]
                }]
            }
            
            # Implement retry logic
            for attempt in range(self.max_retries):
                try:
                    response = requests.post(
                        self.webhook_url,
                        json=payload,
                        timeout=10
                    )
                    response.raise_for_status()
                    # Clear the pools after successful send
                    self.message_pools.clear()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == self.max_retries - 1:  # Last attempt
                        print(f"Error sending digest to Slack after {self.max_retries} attempts: {str(e)}", 
                              file=sys.stderr)
                        
        except Exception as e:
            print(f"Error sending message digest to Slack: {str(e)}", file=sys.stderr)