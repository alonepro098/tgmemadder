#!/bin/bash

# Deployment script for Telegram Member Bot

echo "🚀 Starting deployment..."

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install dependencies
sudo apt-get install -y python3-pip python3-venv postgresql redis-server nginx

# Create project directory
sudo mkdir -p /var/www/telegram-bot
sudo chown $USER:$USER /var/www/telegram-bot

# Copy files
cp -r . /var/www/telegram-bot/

# Setup Python virtual environment
cd /var/www/telegram-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup database
sudo -u postgres psql -c "CREATE DATABASE telegram_bot;"
sudo -u postgres psql -c "CREATE USER telegram_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO telegram_user;"

# Setup environment variables
cat > .env << EOL
DATABASE_URL=postgresql://telegram_user:your_password@localhost:5432/telegram_bot
REDIS_URL=redis://localhost:6379/0
API_ID=your_api_id
API_HASH=your_api_hash
SECRET_KEY=your_secret_key
EOL

# Setup systemd services
sudo cp deploy/telegram-bot.service /etc/systemd/system/
sudo cp deploy/telegram-celery.service /etc/systemd/system/
sudo cp deploy/telegram-celery-beat.service /etc/systemd/system/

# Start services
sudo systemctl daemon-reload
sudo systemctl start telegram-bot
sudo systemctl enable telegram-bot
sudo systemctl start telegram-celery
sudo systemctl enable telegram-celery
sudo systemctl start telegram-celery-beat
sudo systemctl enable telegram-celery-beat

# Setup nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/telegram-bot
sudo ln -s /etc/nginx/sites-available/telegram-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

echo "✅ Deployment complete!"
