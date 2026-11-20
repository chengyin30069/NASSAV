#!/bin/bash
set -euo pipefail

tty_args=()
if [[ -t 0 && -t 1 ]]; then
    tty_args=(-it)
fi

docker run --rm "${tty_args[@]}" \
    -v "<Download Dir>:/MissAV" \
    -v "<missav-cookie.txt dir>:/NASSAV/missav-cookie.txt:ro" \
    nassav "$@"
