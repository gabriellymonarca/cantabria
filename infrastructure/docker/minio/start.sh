#!/bin/sh
# Creates the Langfuse bucket, then starts MinIO on the container addresses.
set -e

mkdir -p /data/langfuse

exec minio server --address ":9000" --console-address ":9001" /data
