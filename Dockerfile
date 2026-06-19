FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set permissions for cron script
RUN chmod +x /app/run_process_reminders.sh

# Configure cron job
RUN echo "* * * * * root /app/run_process_reminders.sh" > /etc/cron.d/process_reminders && \
    chmod 0644 /etc/cron.d/process_reminders && \
    crontab /etc/cron.d/process_reminders

# Create data directory for SQLite
RUN mkdir -p /app/data

# Collect static files
RUN python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 8000

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
