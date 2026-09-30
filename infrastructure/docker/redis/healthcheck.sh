#!/bin/sh
# Reads the password from the mounted redis.conf so it lives in a single file.
set -e

password=$(sed -n 's/^requirepass[[:space:]]*//p' /usr/local/etc/redis/redis.conf)

exec redis-cli --no-auth-warning -a "$password" ping
