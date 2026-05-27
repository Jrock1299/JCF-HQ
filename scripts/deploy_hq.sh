#!/bin/bash
cp "$1" /root/.openclaw/dashboard/jcf_hq.html
cd /root/.openclaw/workspace
cp /root/.openclaw/dashboard/jcf_hq.html dashboard/jcf_hq.html
GIT_SSH_COMMAND='ssh -i /root/.ssh/github_key -o IdentitiesOnly=yes' git add dashboard/jcf_hq.html
GIT_SSH_COMMAND='ssh -i /root/.ssh/github_key -o IdentitiesOnly=yes' git commit -m "HQ: deploy update"
GIT_SSH_COMMAND='ssh -i /root/.ssh/github_key -o IdentitiesOnly=yes' git push origin main
echo "✅ HQ deployed and pushed"
