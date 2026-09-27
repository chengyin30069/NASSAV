#!/bin/bash
set -euo pipefail

docker run --rm \
    -v "<Download Dir>:/MissAV" \
    -v "<missav-cookie.txt dir>:/NASSAV/missav-cookie.txt:ro" \
    nassav "$@"
