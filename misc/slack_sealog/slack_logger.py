"""Slack logging handler that pools messages and sends a digest via incoming webhook."""
import sys
import logging
import requests
from collections import defaultdict
from datetime import datetime
import atexit


class PooledSlackHandler(logging.Handler):
    """Custom logging handler that pools messages and sends them as a single digest"""

    def __init__(self, webhook_url, minimum_level='WARNING', max_retries=3, report_title=None):
        super().__init__()
        self.webhook_url = webhook_url
        self.max_retries = max_retries
        self.report_title = report_title or "Log Summary Report"
        self.setLevel(getattr(logging, minimum_level))

        # Initialize message pools for different log levels
        self.message_pools = defaultdict(list)

        # Register the send_digest method to run at exit
        atexit.register(self.send_digest)

    def emit(self, record):
        """Store the log record in the appropriate pool"""
        try:
            msg = self.format(record)
            # Deduplicate messages by keeping count
            for existing_msg in self.message_pools[record.levelno]:
                if existing_msg['message'] == msg:
                    if 'count' not in existing_msg:
                        existing_msg['count'] = 2
                    else:
                        existing_msg['count'] += 1
                    return

            self.message_pools[record.levelno].append({
                'message': msg,
                'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                'logger': record.name
            })
        except Exception as e:  # pylint: disable=broad-except
            print(f"Error pooling message: {str(e)}", file=sys.stderr)

    def _get_level_name_and_color(self, level):
        """Get Slack formatting for different log levels"""
        if level >= logging.ERROR:
            return "🚨 *Errors*", "#FF0000"
        if level >= logging.WARNING:
            return "⚠️ *Warnings*", "#FFA500"
        if level >= logging.INFO:
            return "ℹ️ *Info*", "#36A64F"
        return "🔍 *Debug*", "#999999"

    def _truncate_message(self, text, max_length=2900):
        """Truncate message if it exceeds max_length"""
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def send_digest(self):
        """Send all pooled messages as a single digest"""
        if not any(self.message_pools.values()):
            return

        try:
            blocks = [{
                'type': 'header',
                'text': {
                    'type': 'plain_text',
                    'text': self.report_title,
                    'emoji': True
                }
            }]
            attachments = [{
                'color': self._get_level_name_and_color(max(self.message_pools.keys()))[1]
            }]

            # Process each level of messages
            for level in sorted(self.message_pools.keys(), reverse=True):
                messages = self.message_pools[level]
                if not messages:
                    continue

                level_name, _ = self._get_level_name_and_color(level)
                message_text = ""

                # Group similar messages
                for msg in messages:
                    count_text = f" (×{msg['count']})" if 'count' in msg else ""
                    message_text += f"• {msg['timestamp']} - {msg['message']}{count_text}\n"

                if message_text:
                    if level == logging.INFO:
                        attachments[0].update({
                            'fallback': f"{self.report_title} - Info",
                            'pretext': level_name,
                            'text': message_text.rstrip(),
                            'mrkdwn_in': ['pretext', 'text']
                        })
                        continue

                    # Split messages if they're too long
                    message_chunks = [
                        message_text[i:i+2900]
                        for i in range(0, len(message_text), 2900)
                    ]

                    blocks.append({
                        'type': 'section',
                        'text': {
                            'type': 'mrkdwn',
                            'text': f"\n{level_name}"
                        }
                    })

                    for chunk in message_chunks:
                        blocks.append({
                            'type': 'section',
                            'text': {
                                'type': 'mrkdwn',
                                'text': chunk
                            }
                        })

                    blocks.append({'type': 'divider'})

            # Remove the last divider if it exists
            if blocks and blocks[-1]['type'] == 'divider':
                blocks.pop()

            # Ensure we don't exceed block limit
            if len(blocks) > 50:
                blocks = blocks[:49]
                blocks.append({
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': "⚠️ *Some messages were truncated due to Slack message limits*"
                    }
                })

            payload = {
                'blocks': blocks,
                'attachments': attachments
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
                    if attempt == self.max_retries - 1:
                        print(
                            f"Error sending digest to Slack after "
                            f"{self.max_retries} attempts: {str(e)}",
                            file=sys.stderr
                        )

        except Exception as e:  # pylint: disable=broad-except
            print(f"Error sending message digest to Slack: {str(e)}", file=sys.stderr)
