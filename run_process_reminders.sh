#!/bin/bash
# Script to run process_reminders Django command from cron with environment variables

set -a
[ -f /etc/environment ] && . /etc/environment
set +a

cd /app
/usr/local/bin/python manage.py process_reminders >> /app/logs/cron.log 2>&1
