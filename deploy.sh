#!/bin/bash

# Deployment script for Telegram Member Adder

echo "🚀 Starting deployment of Telegram Member Adder..."

# Update system & install dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv postgresql redis-server nginx

# Create project directory
INSTALL_DIR="/var/www/telegram-bot"
sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR

# Copy application files
cp -r . $INSTALL_DIR/

# Setup Python virtual environment
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup environment variables
if [ ! -f .env ]; then
    cat > .env << EOL
SECRET_KEY=$(openssl rand -hex 24)
DATABASE_URL=sqlite:////var/www/telegram-bot/telegram_advanced.db
REDIS_URL=redis://localhost:6379/0
API_ID=your_api_id
API_HASH=your_api_hash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
EOL
fi

# Create systemd service for Gunicorn
sudo cat > /etc/systemd/system/telegram-bot.service << EOL
[Unit]
Description=Telegram Member Adder Gunicorn Daemon
After=network.target

[Service]
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/gunicorn --workers 4 --threads 2 --bind 127.0.0.1:5000 app:create_app()
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# Create Nginx config
sudo cat > /etc/nginx/sites-available/telegram-bot << EOL
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOL

sudo ln -sf /etc/nginx/sites-available/telegram-bot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl start telegram-bot
sudo systemctl enable telegram-bot
sudo systemctl restart redis-server
sudo nginx -t && sudo systemctl restart nginx

echo "✅ Deployment complete! Access dashboard at http://<your-server-ip>"
