# OpenClaw exec shell snapshot. Generated; do not edit.
if [ -n "${BASH_VERSION:-}" ]; then shopt -s expand_aliases 2>/dev/null || true; fi
unalias -a 2>/dev/null || true
alias egrep='egrep --color=auto'
alias fgrep='fgrep --color=auto'
alias grep='grep --color=auto'
alias l='ls -CF'
alias la='ls -A'
alias ll='ls -alF'
alias ls='ls --color=auto'
_openclaw_completion () 
{ 
    local cur opts command_path candidate_path value_options word flag i;
    COMPREPLY=();
    cur="${COMP_WORDS[COMP_CWORD]}";
    opts="completion crestodian setup onboard configure config backup migrate doctor dashboard reset uninstall message mcp transcripts agent agents audit status health sessions commitments tasks acp gateway daemon logs system models promos infer capability approvals exec-approvals exec-policy nodes devices node sandbox worktrees attach tui terminal chat cron dns docs proxy hooks webhooks qr clawbot pairing plugins channels directory security secrets skills update --version --container --dev --profile --log-level --no-color";
    value_options="--container --profile --log-level";
    command_path="";
    for ((i = 1; i < COMP_CWORD; i++))
    do
        word="${COMP_WORDS[i]}";
        if [[ ${word} == -* ]]; then
            flag="${word%%=*}";
            if [[ ${word} != *=* && " ${value_options} " == *" ${flag} "* ]]; then
                i=$((i + 1));
            fi;
            continue;
        fi;
        if [[ -n "${command_path}" ]]; then
            candidate_path="${command_path} ${word}";
        else
            candidate_path="${word}";
        fi;
        case "${candidate_path}" in 
            "completion" | "crestodian" | "setup" | "onboard" | "configure" | "config" | "config get" | "config set" | "config patch" | "config unset" | "config file" | "config schema" | "config validate" | "backup" | "backup create" | "backup verify" | "migrate" | "migrate list" | "migrate plan" | "migrate apply" | "doctor" | "dashboard" | "reset" | "uninstall" | "message" | "message send" | "message broadcast" | "message poll" | "message react" | "message reactions" | "message read" | "message edit" | "message delete" | "message pin" | "message unpin" | "message pins" | "message permissions" | "message search" | "message thread" | "message thread create" | "message thread list" | "message thread reply" | "message emoji" | "message emoji list" | "message emoji upload" | "message sticker" | "message sticker send" | "message sticker upload" | "message role" | "message role info" | "message role add" | "message role remove" | "message channel" | "message channel info" | "message channel list" | "message member" | "message member info" | "message voice" | "message voice status" | "message event" | "message event list" | "message event create" | "message timeout" | "message kick" | "message ban" | "mcp" | "mcp serve" | "mcp list" | "mcp show" | "mcp status" | "mcp probe" | "mcp doctor" | "mcp add" | "mcp set" | "mcp tools" | "mcp configure" | "mcp login" | "mcp logout" | "mcp reload" | "mcp unset" | "transcripts" | "transcripts list" | "transcripts show" | "transcripts path" | "agent" | "agents" | "agents list" | "agents bindings" | "agents bind" | "agents unbind" | "agents add" | "agents set-identity" | "agents delete" | "audit" | "status" | "health" | "sessions" | "sessions list" | "sessions cleanup" | "sessions tail" | "sessions export-trajectory" | "sessions compact" | "commitments" | "commitments list" | "commitments dismiss" | "tasks" | "tasks list" | "tasks audit" | "tasks maintenance" | "tasks show" | "tasks notify" | "tasks cancel" | "tasks flow" | "tasks flow list" | "tasks flow show" | "tasks flow cancel" | "acp" | "acp client" | "gateway" | "gateway run" | "gateway status" | "gateway install" | "gateway uninstall" | "gateway start" | "gateway stop" | "gateway restart" | "gateway call" | "gateway usage-cost" | "gateway health" | "gateway stability" | "gateway diagnostics" | "gateway diagnostics export" | "gateway probe" | "gateway discover" | "daemon" | "daemon status" | "daemon install" | "daemon uninstall" | "daemon start" | "daemon stop" | "daemon restart" | "logs" | "system" | "system event" | "system heartbeat" | "system heartbeat last" | "system heartbeat enable" | "system heartbeat disable" | "system presence" | "models" | "models list" | "models status" | "models set" | "models set-image" | "models aliases" | "models aliases list" | "models aliases add" | "models aliases remove" | "models fallbacks" | "models fallbacks list" | "models fallbacks add" | "models fallbacks remove" | "models fallbacks clear" | "models image-fallbacks" | "models image-fallbacks list" | "models image-fallbacks add" | "models image-fallbacks remove" | "models image-fallbacks clear" | "models scan" | "models auth" | "models auth list" | "models auth add" | "models auth login" | "models auth setup-token" | "models auth paste-token" | "models auth paste-api-key" | "models auth login-github-copilot" | "models auth order" | "models auth order get" | "models auth order set" | "models auth order clear" | "promos" | "promos list" | "promos claim" | "infer" | "capability" | "infer list" | "capability list" | "infer inspect" | "capability inspect" | "infer model" | "capability model" | "infer model run" | "capability model run" | "infer model list" | "capability model list" | "infer model inspect" | "capability model inspect" | "infer model providers" | "capability model providers" | "infer model auth" | "capability model auth" | "infer model auth login" | "capability model auth login" | "infer model auth logout" | "capability model auth logout" | "infer model auth status" | "capability model auth status" | "infer image" | "capability image" | "infer image generate" | "capability image generate" | "infer image edit" | "capability image edit" | "infer image describe" | "capability image describe" | "infer image describe-many" | "capability image describe-many" | "infer image providers" | "capability image providers" | "infer audio" | "capability audio" | "infer audio transcribe" | "capability audio transcribe" | "infer audio providers" | "capability audio providers" | "infer tts" | "capability tts" | "infer tts convert" | "capability tts convert" | "infer tts voices" | "capability tts voices" | "infer tts providers" | "capability tts providers" | "infer tts personas" | "capability tts personas" | "infer tts status" | "capability tts status" | "infer tts enable" | "capability tts enable" | "infer tts disable" | "capability tts disable" | "infer tts set-provider" | "capability tts set-provider" | "infer tts set-persona" | "capability tts set-persona" | "infer video" | "capability video" | "infer video generate" | "capability video generate" | "infer video describe" | "capability video describe" | "infer video providers" | "capability video providers" | "infer web" | "capability web" | "infer web search" | "capability web search" | "infer web fetch" | "capability web fetch" | "infer web providers" | "capability web providers" | "infer embedding" | "capability embedding" | "infer embedding create" | "capability embedding create" | "infer embedding providers" | "capability embedding providers" | "approvals" | "exec-approvals" | "approvals get" | "exec-approvals get" | "approvals set" | "exec-approvals set" | "approvals allowlist" | "exec-approvals allowlist" | "approvals allowlist add" | "exec-approvals allowlist add" | "approvals allowlist remove" | "exec-approvals allowlist remove" | "exec-policy" | "exec-policy show" | "exec-policy preset" | "exec-policy set" | "nodes" | "nodes status" | "nodes describe" | "nodes list" | "nodes pending" | "nodes approve" | "nodes reject" | "nodes remove" | "nodes rename" | "nodes invoke" | "nodes notify" | "nodes push" | "nodes camera" | "nodes camera list" | "nodes camera snap" | "nodes camera clip" | "nodes screen" | "nodes screen record" | "nodes location" | "nodes location get" | "nodes canvas" | "nodes canvas snapshot" | "nodes canvas present" | "nodes canvas hide" | "nodes canvas navigate" | "nodes canvas eval" | "nodes canvas a2ui" | "nodes canvas a2ui push" | "nodes canvas a2ui reset" | "devices" | "devices list" | "devices remove" | "devices clear" | "devices approve" | "devices reject" | "devices rotate" | "devices revoke" | "node" | "node run" | "node status" | "node install" | "node uninstall" | "node stop" | "node start" | "node restart" | "sandbox" | "sandbox list" | "sandbox recreate" | "sandbox explain" | "worktrees" | "worktrees list" | "worktrees create" | "worktrees remove" | "worktrees restore" | "worktrees gc" | "attach" | "tui" | "terminal" | "chat" | "cron" | "cron status" | "cron list" | "cron add" | "cron create" | "cron rm" | "cron remove" | "cron delete" | "cron enable" | "cron disable" | "cron get" | "cron show" | "cron runs" | "cron run" | "cron edit" | "dns" | "dns setup" | "docs" | "proxy" | "proxy start" | "proxy run" | "proxy validate" | "proxy coverage" | "proxy sessions" | "proxy query" | "proxy blob" | "proxy purge" | "hooks" | "hooks list" | "hooks info" | "hooks check" | "hooks enable" | "hooks disable" | "hooks relay" | "hooks install" | "hooks update" | "webhooks" | "webhooks gmail" | "webhooks gmail setup" | "webhooks gmail run" | "qr" | "clawbot" | "clawbot qr" | "pairing" | "pairing list" | "pairing approve" | "plugins" | "plugins list" | "plugins search" | "plugins inspect" | "plugins info" | "plugins enable" | "plugins disable" | "plugins uninstall" | "plugins install" | "plugins update" | "plugins registry" | "plugins doctor" | "plugins build" | "plugins validate" | "plugins init" | "plugins marketplace" | "plugins marketplace entries" | "plugins marketplace refresh" | "plugins marketplace list" | "channels" | "channels list" | "channels status" | "channels capabilities" | "channels resolve" | "channels logs" | "channels add" | "channels remove" | "channels login" | "channels logout" | "directory" | "directory self" | "directory peers" | "directory peers list" | "directory groups" | "directory groups list" | "directory groups members" | "security" | "security audit" | "secrets" | "secrets reload" | "secrets audit" | "secrets configure" | "secrets apply" | "skills" | "skills search" | "skills install" | "skills update" | "skills verify" | "skills curator" | "skills curator status" | "skills curator pin" | "skills curator unpin" | "skills curator restore" | "skills workshop" | "skills workshop list" | "skills workshop inspect" | "skills workshop propose-create" | "skills workshop propose-update" | "skills workshop revise" | "skills workshop apply" | "skills workshop reject" | "skills workshop quarantine" | "skills list" | "skills info" | "skills check" | "update" | "update repair" | "update finalize" | "update wizard" | "update status")
                command_path="${candidate_path}";
                case "${command_path}" in 
                    "completion")
                        opts="--shell --install --write-state --yes";
                        value_options="--container --profile --log-level -s --shell"
                    ;;
                    "crestodian")
                        opts="--message --yes --json";
                        value_options="--container --profile --log-level -m --message"
                    ;;
                    "setup")
                        opts="--workspace --wizard --baseline --reset --reset-scope --non-interactive --classic --accept-risk --flow --mode --auth-choice --token-provider --token --token-profile-id --token-expires-in --secret-input-mode --cloudflare-ai-gateway-account-id --cloudflare-ai-gateway-gateway-id --alibaba-model-studio-api-key --anthropic-api-key --byteplus-api-key --clawrouter-api-key --cohere-api-key --comfy-api-key --fal-api-key --github-copilot-token --gemini-api-key --huggingface-api-key --litellm-api-key --lmstudio-api-key --meta-api-key --minimax-api-key --mistral-api-key --novita-api-key --nvidia-api-key --ollama-cloud-api-key --openai-api-key --opencode-zen-api-key --opencode-go-api-key --openrouter-api-key --runway-api-key --synthetic-api-key --together-api-key --volcengine-api-key --vydra-api-key --xai-api-key --xiaomi-api-key --xiaomi-token-plan-api-key --kimi-code-api-key --moonshot-api-key --arceeai-api-key --cerebras-api-key --chutes-api-key --cloudflare-ai-gateway-api-key --deepinfra-api-key --deepseek-api-key --featherless-api-key --gmi-api-key --longcat-api-key --groq-api-key --kilocode-api-key --pixverse-api-key --qianfan-api-key --modelstudio-standard-api-key-cn --modelstudio-standard-api-key --modelstudio-api-key-cn --modelstudio-api-key --qwen-oauth-token --fireworks-api-key --tokenhub-api-key --tokenplan-api-key --venice-api-key --ai-gateway-api-key --zai-api-key --stepfun-api-key --custom-base-url --custom-api-key --custom-model-id --custom-provider-id --custom-compatibility --custom-image-input --custom-text-input --gateway-port --gateway-bind --gateway-auth --gateway-token --gateway-token-ref-env --gateway-password --tailscale --tailscale-reset-on-exit --install-daemon --no-install-daemon --skip-daemon --daemon-runtime --skip-channels --skip-skills --skip-bootstrap --skip-search --skip-health --skip-ui --suppress-gateway-token-output --skip-hooks --node-manager --import-from --import-source --import-secrets --remote-url --remote-token --json";
                        value_options="--container --profile --log-level --workspace --reset-scope --flow --mode --auth-choice --token-provider --token --token-profile-id --token-expires-in --secret-input-mode --cloudflare-ai-gateway-account-id --cloudflare-ai-gateway-gateway-id --alibaba-model-studio-api-key --anthropic-api-key --byteplus-api-key --clawrouter-api-key --cohere-api-key --comfy-api-key --fal-api-key --github-copilot-token --gemini-api-key --huggingface-api-key --litellm-api-key --lmstudio-api-key --meta-api-key --minimax-api-key --mistral-api-key --novita-api-key --nvidia-api-key --ollama-cloud-api-key --openai-api-key --opencode-zen-api-key --opencode-go-api-key --openrouter-api-key --runway-api-key --synthetic-api-key --together-api-key --volcengine-api-key --vydra-api-key --xai-api-key --xiaomi-api-key --xiaomi-token-plan-api-key --kimi-code-api-key --moonshot-api-key --arceeai-api-key --cerebras-api-key --chutes-api-key --cloudflare-ai-gateway-api-key --deepinfra-api-key --deepseek-api-key --featherless-api-key --gmi-api-key --longcat-api-key --groq-api-key --kilocode-api-key --pixverse-api-key --qianfan-api-key --modelstudio-standard-api-key-cn --modelstudio-standard-api-key --modelstudio-api-key-cn --modelstudio-api-key --qwen-oauth-token --fireworks-api-key --tokenhub-api-key --tokenplan-api-key --venice-api-key --ai-gateway-api-key --zai-api-key --stepfun-api-key --custom-base-url --custom-api-key --custom-model-id --custom-provider-id --custom-compatibility --gateway-port --gateway-bind --gateway-auth --gateway-token --gateway-token-ref-env --gateway-password --tailscale --daemon-runtime --node-manager --import-from --import-source --remote-url --remote-token"
                    ;;
                    "onboard")
                        opts="--workspace --reset --reset-scope --non-interactive --modern --classic --accept-risk --flow --mode --auth-choice --token-provider --token --token-profile-id --token-expires-in --secret-input-mode --cloudflare-ai-gateway-account-id --cloudflare-ai-gateway-gateway-id --alibaba-model-studio-api-key --anthropic-api-key --byteplus-api-key --clawrouter-api-key --cohere-api-key --comfy-api-key --fal-api-key --github-copilot-token --gemini-api-key --huggingface-api-key --litellm-api-key --lmstudio-api-key --meta-api-key --minimax-api-key --mistral-api-key --novita-api-key --nvidia-api-key --ollama-cloud-api-key --openai-api-key --opencode-zen-api-key --opencode-go-api-key --openrouter-api-key --runway-api-key --synthetic-api-key --together-api-key --volcengine-api-key --vydra-api-key --xai-api-key --xiaomi-api-key --xiaomi-token-plan-api-key --kimi-code-api-key --moonshot-api-key --arceeai-api-key --cerebras-api-key --chutes-api-key --cloudflare-ai-gateway-api-key --deepinfra-api-key --deepseek-api-key --featherless-api-key --gmi-api-key --longcat-api-key --groq-api-key --kilocode-api-key --pixverse-api-key --qianfan-api-key --modelstudio-standard-api-key-cn --modelstudio-standard-api-key --modelstudio-api-key-cn --modelstudio-api-key --qwen-oauth-token --fireworks-api-key --tokenhub-api-key --tokenplan-api-key --venice-api-key --ai-gateway-api-key --zai-api-key --stepfun-api-key --custom-base-url --custom-api-key --custom-model-id --custom-provider-id --custom-compatibility --custom-image-input --custom-text-input --gateway-port --gateway-bind --gateway-auth --gateway-token --gateway-token-ref-env --gateway-password --remote-url --remote-token --tailscale --tailscale-reset-on-exit --install-daemon --no-install-daemon --skip-daemon --daemon-runtime --skip-channels --skip-skills --skip-bootstrap --skip-search --skip-health --skip-ui --suppress-gateway-token-output --skip-hooks --node-manager --import-from --import-source --import-secrets --json";
                        value_options="--container --profile --log-level --workspace --reset-scope --flow --mode --auth-choice --token-provider --token --token-profile-id --token-expires-in --secret-input-mode --cloudflare-ai-gateway-account-id --cloudflare-ai-gateway-gateway-id --alibaba-model-studio-api-key --anthropic-api-key --byteplus-api-key --clawrouter-api-key --cohere-api-key --comfy-api-key --fal-api-key --github-copilot-token --gemini-api-key --huggingface-api-key --litellm-api-key --lmstudio-api-key --meta-api-key --minimax-api-key --mistral-api-key --novita-api-key --nvidia-api-key --ollama-cloud-api-key --openai-api-key --opencode-zen-api-key --opencode-go-api-key --openrouter-api-key --runway-api-key --synthetic-api-key --together-api-key --volcengine-api-key --vydra-api-key --xai-api-key --xiaomi-api-key --xiaomi-token-plan-api-key --kimi-code-api-key --moonshot-api-key --arceeai-api-key --cerebras-api-key --chutes-api-key --cloudflare-ai-gateway-api-key --deepinfra-api-key --deepseek-api-key --featherless-api-key --gmi-api-key --longcat-api-key --groq-api-key --kilocode-api-key --pixverse-api-key --qianfan-api-key --modelstudio-standard-api-key-cn --modelstudio-standard-api-key --modelstudio-api-key-cn --modelstudio-api-key --qwen-oauth-token --fireworks-api-key --tokenhub-api-key --tokenplan-api-key --venice-api-key --ai-gateway-api-key --zai-api-key --stepfun-api-key --custom-base-url --custom-api-key --custom-model-id --custom-provider-id --custom-compatibility --gateway-port --gateway-bind --gateway-auth --gateway-token --gateway-token-ref-env --gateway-password --remote-url --remote-token --tailscale --daemon-runtime --node-manager --import-from --import-source"
                    ;;
                    "configure")
                        opts="--section";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config")
                        opts="get set patch unset file schema validate --section";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config get")
                        opts="--json";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config set")
                        opts="--strict-json --json --dry-run --allow-exec --merge --replace --ref-provider --ref-source --ref-id --provider-source --provider-allowlist --provider-path --provider-mode --provider-timeout-ms --provider-max-bytes --provider-command --provider-arg --provider-no-output-timeout-ms --provider-max-output-bytes --provider-json-only --provider-env --provider-pass-env --provider-trusted-dir --provider-allow-insecure-path --provider-allow-symlink-command --batch-json --batch-file";
                        value_options="--container --profile --log-level --section --ref-provider --ref-source --ref-id --provider-source --provider-allowlist --provider-path --provider-mode --provider-timeout-ms --provider-max-bytes --provider-command --provider-arg --provider-no-output-timeout-ms --provider-max-output-bytes --provider-env --provider-pass-env --provider-trusted-dir --batch-json --batch-file"
                    ;;
                    "config patch")
                        opts="--file --stdin --dry-run --allow-exec --json --replace-path";
                        value_options="--container --profile --log-level --section --file --replace-path"
                    ;;
                    "config unset")
                        opts="--dry-run --allow-exec --json";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config file")
                        opts="";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config schema")
                        opts="";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "config validate")
                        opts="--json";
                        value_options="--container --profile --log-level --section"
                    ;;
                    "backup")
                        opts="create verify";
                        value_options="--container --profile --log-level"
                    ;;
                    "backup create")
                        opts="--output --json --dry-run --verify --only-config --no-include-workspace";
                        value_options="--container --profile --log-level --output"
                    ;;
                    "backup verify")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "migrate")
                        opts="list plan apply --from --include-secrets --no-auth-credentials --overwrite --dry-run --yes --skill --plugin --backup-output --no-backup --force --json --verify-plugin-apps";
                        value_options="--container --profile --log-level --from --skill --plugin --backup-output"
                    ;;
                    "migrate list")
                        opts="--json";
                        value_options="--container --profile --log-level --from --skill --plugin --backup-output"
                    ;;
                    "migrate plan")
                        opts="--from --include-secrets --no-auth-credentials --overwrite --json --skill --plugin --verify-plugin-apps";
                        value_options="--container --profile --log-level --from --skill --plugin --backup-output"
                    ;;
                    "migrate apply")
                        opts="--from --include-secrets --no-auth-credentials --overwrite --json --skill --plugin --verify-plugin-apps --yes --backup-output --no-backup --force";
                        value_options="--container --profile --log-level --from --skill --plugin --backup-output"
                    ;;
                    "doctor")
                        opts="--no-workspace-suggestions --yes --repair --fix --force --non-interactive --generate-gateway-token --allow-exec --deep --lint --post-upgrade --json --severity-min --all --skip --only";
                        value_options="--container --profile --log-level --severity-min --skip --only"
                    ;;
                    "dashboard")
                        opts="--no-open --yes";
                        value_options="--container --profile --log-level"
                    ;;
                    "reset")
                        opts="--scope --yes --non-interactive --dry-run";
                        value_options="--container --profile --log-level --scope"
                    ;;
                    "uninstall")
                        opts="--service --state --workspace --app --all --yes --non-interactive --dry-run";
                        value_options="--container --profile --log-level"
                    ;;
                    "message")
                        opts="send broadcast poll react reactions read edit delete pin unpin pins permissions search thread emoji sticker role channel member voice event timeout kick ban";
                        value_options="--container --profile --log-level"
                    ;;
                    "message send")
                        opts="--message --target --media --presentation --delivery --pin --reply-to --thread-id --gif-playback --force-document --silent --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level -m --message -t --target --media --presentation --delivery --reply-to --thread-id --channel --account"
                    ;;
                    "message broadcast")
                        opts="--channel --account --json --dry-run --verbose --targets --message --media";
                        value_options="--container --profile --log-level --channel --account --targets --message --media"
                    ;;
                    "message poll")
                        opts="--target --channel --account --json --dry-run --verbose --poll-question --poll-option --poll-multi --poll-duration-hours --poll-duration-seconds --poll-anonymous --poll-public --message --silent --thread-id";
                        value_options="--container --profile --log-level -t --target --channel --account --poll-question --poll-option --poll-duration-hours --poll-duration-seconds -m --message --thread-id"
                    ;;
                    "message react")
                        opts="--target --channel --account --json --dry-run --verbose --message-id --emoji --remove --participant --from-me --target-author --target-author-uuid";
                        value_options="--container --profile --log-level -t --target --channel --account --message-id --emoji --participant --target-author --target-author-uuid"
                    ;;
                    "message reactions")
                        opts="--target --channel --account --json --dry-run --verbose --message-id --limit";
                        value_options="--container --profile --log-level -t --target --channel --account --message-id --limit"
                    ;;
                    "message read")
                        opts="--target --channel --account --json --dry-run --verbose --limit --message-id --before --after --around --thread-id --include-thread";
                        value_options="--container --profile --log-level -t --target --channel --account --limit --message-id --before --after --around --thread-id"
                    ;;
                    "message edit")
                        opts="--message-id --message --target --channel --account --json --dry-run --verbose --thread-id";
                        value_options="--container --profile --log-level --message-id -m --message -t --target --channel --account --thread-id"
                    ;;
                    "message delete")
                        opts="--message-id --target --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --message-id -t --target --channel --account"
                    ;;
                    "message pin")
                        opts="--target --channel --account --json --dry-run --verbose --message-id";
                        value_options="--container --profile --log-level -t --target --channel --account --message-id"
                    ;;
                    "message unpin")
                        opts="--target --channel --account --json --dry-run --verbose --message-id --pinned-message-id";
                        value_options="--container --profile --log-level -t --target --channel --account --message-id --pinned-message-id"
                    ;;
                    "message pins")
                        opts="--target --channel --account --json --dry-run --verbose --limit";
                        value_options="--container --profile --log-level -t --target --channel --account --limit"
                    ;;
                    "message permissions")
                        opts="--target --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level -t --target --channel --account"
                    ;;
                    "message search")
                        opts="--channel --account --json --dry-run --verbose --guild-id --query --channel-id --channel-ids --author-id --author-ids --limit";
                        value_options="--container --profile --log-level --channel --account --guild-id --query --channel-id --channel-ids --author-id --author-ids --limit"
                    ;;
                    "message thread")
                        opts="create list reply";
                        value_options="--container --profile --log-level"
                    ;;
                    "message thread create")
                        opts="--thread-name --target --channel --account --json --dry-run --verbose --message-id --message --auto-archive-min";
                        value_options="--container --profile --log-level --thread-name -t --target --channel --account --message-id -m --message --auto-archive-min"
                    ;;
                    "message thread list")
                        opts="--guild-id --channel --account --json --dry-run --verbose --channel-id --include-archived --before --limit";
                        value_options="--container --profile --log-level --guild-id --channel --account --channel-id --before --limit"
                    ;;
                    "message thread reply")
                        opts="--message --target --channel --account --json --dry-run --verbose --media --reply-to";
                        value_options="--container --profile --log-level -m --message -t --target --channel --account --media --reply-to"
                    ;;
                    "message emoji")
                        opts="list upload";
                        value_options="--container --profile --log-level"
                    ;;
                    "message emoji list")
                        opts="--channel --account --json --dry-run --verbose --guild-id";
                        value_options="--container --profile --log-level --channel --account --guild-id"
                    ;;
                    "message emoji upload")
                        opts="--guild-id --channel --account --json --dry-run --verbose --emoji-name --media --role-ids";
                        value_options="--container --profile --log-level --guild-id --channel --account --emoji-name --media --role-ids"
                    ;;
                    "message sticker")
                        opts="send upload";
                        value_options="--container --profile --log-level"
                    ;;
                    "message sticker send")
                        opts="--target --channel --account --json --dry-run --verbose --sticker-id --message";
                        value_options="--container --profile --log-level -t --target --channel --account --sticker-id -m --message"
                    ;;
                    "message sticker upload")
                        opts="--guild-id --channel --account --json --dry-run --verbose --sticker-name --sticker-desc --sticker-tags --media";
                        value_options="--container --profile --log-level --guild-id --channel --account --sticker-name --sticker-desc --sticker-tags --media"
                    ;;
                    "message role")
                        opts="info add remove";
                        value_options="--container --profile --log-level"
                    ;;
                    "message role info")
                        opts="--guild-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --channel --account"
                    ;;
                    "message role add")
                        opts="--guild-id --user-id --role-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --user-id --role-id --channel --account"
                    ;;
                    "message role remove")
                        opts="--guild-id --user-id --role-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --user-id --role-id --channel --account"
                    ;;
                    "message channel")
                        opts="info list";
                        value_options="--container --profile --log-level"
                    ;;
                    "message channel info")
                        opts="--target --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level -t --target --channel --account"
                    ;;
                    "message channel list")
                        opts="--guild-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --channel --account"
                    ;;
                    "message member")
                        opts="info";
                        value_options="--container --profile --log-level"
                    ;;
                    "message member info")
                        opts="--user-id --channel --account --json --dry-run --verbose --guild-id";
                        value_options="--container --profile --log-level --user-id --channel --account --guild-id"
                    ;;
                    "message voice")
                        opts="status";
                        value_options="--container --profile --log-level"
                    ;;
                    "message voice status")
                        opts="--guild-id --user-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --user-id --channel --account"
                    ;;
                    "message event")
                        opts="list create";
                        value_options="--container --profile --log-level"
                    ;;
                    "message event list")
                        opts="--guild-id --channel --account --json --dry-run --verbose";
                        value_options="--container --profile --log-level --guild-id --channel --account"
                    ;;
                    "message event create")
                        opts="--guild-id --event-name --start-time --channel --account --json --dry-run --verbose --end-time --desc --channel-id --location --event-type --image";
                        value_options="--container --profile --log-level --guild-id --event-name --start-time --channel --account --end-time --desc --channel-id --location --event-type --image"
                    ;;
                    "message timeout")
                        opts="--guild-id --user-id --channel --account --json --dry-run --verbose --duration-min --until --reason";
                        value_options="--container --profile --log-level --guild-id --user-id --channel --account --duration-min --until --reason"
                    ;;
                    "message kick")
                        opts="--guild-id --user-id --channel --account --json --dry-run --verbose --reason";
                        value_options="--container --profile --log-level --guild-id --user-id --channel --account --reason"
                    ;;
                    "message ban")
                        opts="--guild-id --user-id --channel --account --json --dry-run --verbose --reason --delete-days";
                        value_options="--container --profile --log-level --guild-id --user-id --channel --account --reason --delete-days"
                    ;;
                    "mcp")
                        opts="serve list show status probe doctor add set tools configure login logout reload unset";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp serve")
                        opts="--url --token --token-file --password --password-file --claude-channel-mode --verbose";
                        value_options="--container --profile --log-level --url --token --token-file --password --password-file --claude-channel-mode"
                    ;;
                    "mcp list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp show")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp status")
                        opts="--verbose --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp probe")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp doctor")
                        opts="--probe --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp add")
                        opts="--command --arg --env --cwd --url --transport --header --auth --oauth-scope --oauth-redirect-url --oauth-client-metadata-url --include --exclude --timeout --connect-timeout --parallel --disabled --ssl-verify --client-cert --client-key --no-probe";
                        value_options="--container --profile --log-level --command --arg --env --cwd --url --transport --header --auth --oauth-scope --oauth-redirect-url --oauth-client-metadata-url --include --exclude --timeout --connect-timeout --ssl-verify --client-cert --client-key"
                    ;;
                    "mcp set")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp tools")
                        opts="--include --exclude --clear";
                        value_options="--container --profile --log-level --include --exclude"
                    ;;
                    "mcp configure")
                        opts="--enable --disable --include --exclude --clear-tools --timeout --connect-timeout --clear-timeouts --parallel --no-parallel --auth --clear-auth --oauth-scope --oauth-redirect-url --oauth-client-metadata-url --ssl-verify --client-cert --client-key --clear-tls --probe";
                        value_options="--container --profile --log-level --include --exclude --timeout --connect-timeout --auth --oauth-scope --oauth-redirect-url --oauth-client-metadata-url --ssl-verify --client-cert --client-key"
                    ;;
                    "mcp login")
                        opts="--code";
                        value_options="--container --profile --log-level --code"
                    ;;
                    "mcp logout")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp reload")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "mcp unset")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "transcripts")
                        opts="list show path";
                        value_options="--container --profile --log-level"
                    ;;
                    "transcripts list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "transcripts show")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "transcripts path")
                        opts="--dir --metadata --transcript --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "agent")
                        opts="--message --message-file --to --session-key --session-id --agent --model --thinking --verbose --channel --reply-to --reply-channel --reply-account --local --deliver --json --timeout";
                        value_options="--container --profile --log-level -m --message --message-file -t --to --session-key --session-id --agent --model --thinking --verbose --channel --reply-to --reply-channel --reply-account --timeout"
                    ;;
                    "agents")
                        opts="list bindings bind unbind add set-identity delete";
                        value_options="--container --profile --log-level"
                    ;;
                    "agents list")
                        opts="--json --bindings";
                        value_options="--container --profile --log-level"
                    ;;
                    "agents bindings")
                        opts="--agent --json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "agents bind")
                        opts="--agent --bind --json";
                        value_options="--container --profile --log-level --agent --bind"
                    ;;
                    "agents unbind")
                        opts="--agent --bind --all --json";
                        value_options="--container --profile --log-level --agent --bind"
                    ;;
                    "agents add")
                        opts="--workspace --model --agent-dir --bind --non-interactive --json";
                        value_options="--container --profile --log-level --workspace --model --agent-dir --bind"
                    ;;
                    "agents set-identity")
                        opts="--agent --workspace --identity-file --from-identity --name --theme --emoji --avatar --json";
                        value_options="--container --profile --log-level --agent --workspace --identity-file --name --theme --emoji --avatar"
                    ;;
                    "agents delete")
                        opts="--force --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "audit")
                        opts="--agent --session --run --kind --status --after --before --cursor --limit --json";
                        value_options="--container --profile --log-level --agent --session --run --kind --status --after --before --cursor --limit"
                    ;;
                    "status")
                        opts="--json --all --usage --deep --timeout --verbose --debug";
                        value_options="--container --profile --log-level --timeout"
                    ;;
                    "health")
                        opts="--json --timeout --verbose --debug";
                        value_options="--container --profile --log-level --timeout"
                    ;;
                    "sessions")
                        opts="list cleanup tail export-trajectory compact --json --verbose --store --agent --all-agents --active --limit";
                        value_options="--container --profile --log-level --store --agent --active --limit"
                    ;;
                    "sessions list")
                        opts="--json --verbose --store --agent --all-agents --active --limit";
                        value_options="--container --profile --log-level --store --agent --active --limit"
                    ;;
                    "sessions cleanup")
                        opts="--store --agent --all-agents --dry-run --enforce --fix-missing --fix-dm-scope --active-key --json";
                        value_options="--container --profile --log-level --store --agent --active --limit --active-key"
                    ;;
                    "sessions tail")
                        opts="--session-key --tail --follow --store --agent --all-agents";
                        value_options="--container --profile --log-level --store --agent --active --limit --session-key --tail"
                    ;;
                    "sessions export-trajectory")
                        opts="--session-key --output --workspace --store --agent --request-json-base64 --json";
                        value_options="--container --profile --log-level --store --agent --active --limit --session-key --output --workspace --request-json-base64"
                    ;;
                    "sessions compact")
                        opts="--agent --max-lines --url --token --password --timeout --json";
                        value_options="--container --profile --log-level --store --agent --active --limit --max-lines --url --token --password --timeout"
                    ;;
                    "commitments")
                        opts="list dismiss --json --agent --status --all";
                        value_options="--container --profile --log-level --agent --status"
                    ;;
                    "commitments list")
                        opts="--json --agent --status --all";
                        value_options="--container --profile --log-level --agent --status"
                    ;;
                    "commitments dismiss")
                        opts="--json";
                        value_options="--container --profile --log-level --agent --status"
                    ;;
                    "tasks")
                        opts="list audit maintenance show notify cancel flow --json --runtime --status";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks list")
                        opts="--json --runtime --status";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks audit")
                        opts="--json --severity --code --limit";
                        value_options="--container --profile --log-level --runtime --status --severity --code --limit"
                    ;;
                    "tasks maintenance")
                        opts="--json --apply";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks show")
                        opts="--json";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks notify")
                        opts="";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks cancel")
                        opts="";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks flow")
                        opts="list show cancel";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks flow list")
                        opts="--json --status";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks flow show")
                        opts="--json";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "tasks flow cancel")
                        opts="";
                        value_options="--container --profile --log-level --runtime --status"
                    ;;
                    "acp")
                        opts="client --url --token --token-file --password --password-file --session --session-label --require-existing --reset-session --no-prefix-cwd --provenance --verbose";
                        value_options="--container --profile --log-level --url --token --token-file --password --password-file --session --session-label --provenance"
                    ;;
                    "acp client")
                        opts="--cwd --server --server-args --server-verbose --verbose";
                        value_options="--container --profile --log-level --url --token --token-file --password --password-file --session --session-label --provenance --cwd --server --server-args"
                    ;;
                    "gateway")
                        opts="run status install uninstall start stop restart call usage-cost health stability diagnostics probe discover --port --bind --token --auth --password --password-file --tailscale --tailscale-reset-on-exit --allow-unconfigured --dev --reset --force --verbose --cli-backend-logs --claude-cli-logs --ws-log --compact --raw-stream --raw-stream-path";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway run")
                        opts="--port --bind --token --auth --password --password-file --tailscale --tailscale-reset-on-exit --allow-unconfigured --dev --reset --force --verbose --cli-backend-logs --claude-cli-logs --ws-log --compact --raw-stream --raw-stream-path";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway status")
                        opts="--url --token --password --timeout --no-probe --require-rpc --deep --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --url --timeout"
                    ;;
                    "gateway install")
                        opts="--port --runtime --token --wrapper --force --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --runtime --wrapper"
                    ;;
                    "gateway uninstall")
                        opts="--json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway start")
                        opts="--json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway stop")
                        opts="--json --disable";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway restart")
                        opts="--force --safe --skip-deferral --wait --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --wait"
                    ;;
                    "gateway call")
                        opts="--params --url --token --password --timeout --expect-final --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --params --url --timeout"
                    ;;
                    "gateway usage-cost")
                        opts="--days --agent --all-agents --url --token --password --timeout --expect-final --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --days --agent --url --timeout"
                    ;;
                    "gateway health")
                        opts="--port --url --token --password --timeout --expect-final --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --url --timeout"
                    ;;
                    "gateway stability")
                        opts="--limit --type --since-seq --bundle --export --output --url --token --password --timeout --expect-final --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --limit --type --since-seq --bundle --output --url --timeout"
                    ;;
                    "gateway diagnostics")
                        opts="export";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path"
                    ;;
                    "gateway diagnostics export")
                        opts="--output --log-lines --log-bytes --url --token --password --timeout --no-stability-bundle --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --output --log-lines --log-bytes --url --timeout"
                    ;;
                    "gateway probe")
                        opts="--url --port --ssh --ssh-identity --ssh-auto --token --password --timeout --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --url --ssh --ssh-identity --timeout"
                    ;;
                    "gateway discover")
                        opts="--timeout --json";
                        value_options="--container --profile --log-level --port --bind --token --auth --password --password-file --tailscale --ws-log --raw-stream-path --timeout"
                    ;;
                    "daemon")
                        opts="status install uninstall start stop restart";
                        value_options="--container --profile --log-level"
                    ;;
                    "daemon status")
                        opts="--url --token --password --timeout --no-probe --require-rpc --deep --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "daemon install")
                        opts="--port --runtime --token --wrapper --force --json";
                        value_options="--container --profile --log-level --port --runtime --token --wrapper"
                    ;;
                    "daemon uninstall")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "daemon start")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "daemon stop")
                        opts="--json --disable";
                        value_options="--container --profile --log-level"
                    ;;
                    "daemon restart")
                        opts="--force --safe --skip-deferral --wait --json";
                        value_options="--container --profile --log-level --wait"
                    ;;
                    "logs")
                        opts="--limit --max-bytes --follow --interval --json --plain --no-color --local-time --utc --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --limit --max-bytes --interval --url --token --timeout"
                    ;;
                    "system")
                        opts="event heartbeat presence";
                        value_options="--container --profile --log-level"
                    ;;
                    "system event")
                        opts="--text --mode --session-key --json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --text --mode --session-key --url --token --timeout"
                    ;;
                    "system heartbeat")
                        opts="last enable disable";
                        value_options="--container --profile --log-level"
                    ;;
                    "system heartbeat last")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "system heartbeat enable")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "system heartbeat disable")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "system presence")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "models")
                        opts="list status set set-image aliases fallbacks image-fallbacks scan auth --status-json --status-plain --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models list")
                        opts="--all --local --provider --json --plain";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "models status")
                        opts="--json --plain --check --probe --probe-provider --probe-profile --probe-timeout --probe-concurrency --probe-max-tokens --agent";
                        value_options="--container --profile --log-level --agent --probe-provider --probe-profile --probe-timeout --probe-concurrency --probe-max-tokens"
                    ;;
                    "models set")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models set-image")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models aliases")
                        opts="list add remove";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models aliases list")
                        opts="--json --plain";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models aliases add")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models aliases remove")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models fallbacks")
                        opts="list add remove clear";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models fallbacks list")
                        opts="--json --plain";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models fallbacks add")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models fallbacks remove")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models fallbacks clear")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models image-fallbacks")
                        opts="list add remove clear";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models image-fallbacks list")
                        opts="--json --plain";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models image-fallbacks add")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models image-fallbacks remove")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models image-fallbacks clear")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models scan")
                        opts="--min-params --max-age-days --provider --max-candidates --timeout --concurrency --no-probe --yes --no-input --set-default --set-image --json";
                        value_options="--container --profile --log-level --agent --min-params --max-age-days --provider --max-candidates --timeout --concurrency"
                    ;;
                    "models auth")
                        opts="list add login setup-token paste-token paste-api-key login-github-copilot order --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models auth list")
                        opts="--provider --agent --json";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "models auth add")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models auth login")
                        opts="--provider --method --device-code --profile-id --set-default --force";
                        value_options="--container --profile --log-level --agent --provider --method --profile-id"
                    ;;
                    "models auth setup-token")
                        opts="--provider --yes";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "models auth paste-token")
                        opts="--provider --profile-id --expires-in";
                        value_options="--container --profile --log-level --agent --provider --profile-id --expires-in"
                    ;;
                    "models auth paste-api-key")
                        opts="--provider --profile-id";
                        value_options="--container --profile --log-level --agent --provider --profile-id"
                    ;;
                    "models auth login-github-copilot")
                        opts="--yes";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models auth order")
                        opts="get set clear";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "models auth order get")
                        opts="--provider --agent --json";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "models auth order set")
                        opts="--provider --agent";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "models auth order clear")
                        opts="--provider --agent";
                        value_options="--container --profile --log-level --agent --provider"
                    ;;
                    "promos")
                        opts="list claim";
                        value_options="--container --profile --log-level"
                    ;;
                    "promos list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "promos claim")
                        opts="--api-key --set-default";
                        value_options="--container --profile --log-level --api-key"
                    ;;
                    "infer" | "capability")
                        opts="list inspect model image audio tts video web embedding";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer list" | "capability list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer inspect" | "capability inspect")
                        opts="--name --json";
                        value_options="--container --profile --log-level --name"
                    ;;
                    "infer model" | "capability model")
                        opts="run list inspect providers auth";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer model run" | "capability model run")
                        opts="--prompt --file --model --thinking --local --gateway --json";
                        value_options="--container --profile --log-level --prompt --file --model --thinking"
                    ;;
                    "infer model list" | "capability model list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer model inspect" | "capability model inspect")
                        opts="--model --json";
                        value_options="--container --profile --log-level --model"
                    ;;
                    "infer model providers" | "capability model providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer model auth" | "capability model auth")
                        opts="login logout status";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer model auth login" | "capability model auth login")
                        opts="--provider --method";
                        value_options="--container --profile --log-level --provider --method"
                    ;;
                    "infer model auth logout" | "capability model auth logout")
                        opts="--provider --agent --json";
                        value_options="--container --profile --log-level --provider --agent"
                    ;;
                    "infer model auth status" | "capability model auth status")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer image" | "capability image")
                        opts="generate edit describe describe-many providers";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer image generate" | "capability image generate")
                        opts="--prompt --model --count --size --aspect-ratio --resolution --output-format --background --openai-background --openai-moderation --quality --timeout-ms --output --json";
                        value_options="--container --profile --log-level --prompt --model --count --size --aspect-ratio --resolution --output-format --background --openai-background --openai-moderation --quality --timeout-ms --output"
                    ;;
                    "infer image edit" | "capability image edit")
                        opts="--file --prompt --model --count --size --aspect-ratio --resolution --output-format --background --openai-background --openai-moderation --quality --timeout-ms --output --json";
                        value_options="--container --profile --log-level --file --prompt --model --count --size --aspect-ratio --resolution --output-format --background --openai-background --openai-moderation --quality --timeout-ms --output"
                    ;;
                    "infer image describe" | "capability image describe")
                        opts="--file --prompt --model --timeout-ms --json";
                        value_options="--container --profile --log-level --file --prompt --model --timeout-ms"
                    ;;
                    "infer image describe-many" | "capability image describe-many")
                        opts="--file --prompt --model --timeout-ms --json";
                        value_options="--container --profile --log-level --file --prompt --model --timeout-ms"
                    ;;
                    "infer image providers" | "capability image providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer audio" | "capability audio")
                        opts="transcribe providers";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer audio transcribe" | "capability audio transcribe")
                        opts="--file --language --prompt --model --json";
                        value_options="--container --profile --log-level --file --language --prompt --model"
                    ;;
                    "infer audio providers" | "capability audio providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts" | "capability tts")
                        opts="convert voices providers personas status enable disable set-provider set-persona";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts convert" | "capability tts convert")
                        opts="--text --channel --voice --model --output --local --gateway --json";
                        value_options="--container --profile --log-level --text --channel --voice --model --output"
                    ;;
                    "infer tts voices" | "capability tts voices")
                        opts="--provider --json";
                        value_options="--container --profile --log-level --provider"
                    ;;
                    "infer tts providers" | "capability tts providers")
                        opts="--local --gateway --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts personas" | "capability tts personas")
                        opts="--local --gateway --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts status" | "capability tts status")
                        opts="--gateway --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts enable" | "capability tts enable")
                        opts="--local --gateway --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts disable" | "capability tts disable")
                        opts="--local --gateway --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer tts set-provider" | "capability tts set-provider")
                        opts="--provider --local --gateway --json";
                        value_options="--container --profile --log-level --provider"
                    ;;
                    "infer tts set-persona" | "capability tts set-persona")
                        opts="--persona --off --local --gateway --json";
                        value_options="--container --profile --log-level --persona"
                    ;;
                    "infer video" | "capability video")
                        opts="generate describe providers";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer video generate" | "capability video generate")
                        opts="--prompt --model --size --aspect-ratio --resolution --duration --audio --watermark --timeout-ms --output --json";
                        value_options="--container --profile --log-level --prompt --model --size --aspect-ratio --resolution --duration --timeout-ms --output"
                    ;;
                    "infer video describe" | "capability video describe")
                        opts="--file --model --json";
                        value_options="--container --profile --log-level --file --model"
                    ;;
                    "infer video providers" | "capability video providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer web" | "capability web")
                        opts="search fetch providers";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer web search" | "capability web search")
                        opts="--query --provider --limit --json";
                        value_options="--container --profile --log-level --query --provider --limit"
                    ;;
                    "infer web fetch" | "capability web fetch")
                        opts="--url --provider --format --json";
                        value_options="--container --profile --log-level --url --provider --format"
                    ;;
                    "infer web providers" | "capability web providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer embedding" | "capability embedding")
                        opts="create providers";
                        value_options="--container --profile --log-level"
                    ;;
                    "infer embedding create" | "capability embedding create")
                        opts="--text --provider --model --json";
                        value_options="--container --profile --log-level --text --provider --model"
                    ;;
                    "infer embedding providers" | "capability embedding providers")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "approvals" | "exec-approvals")
                        opts="get set allowlist";
                        value_options="--container --profile --log-level"
                    ;;
                    "approvals get" | "exec-approvals get")
                        opts="--node --gateway --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --url --token --timeout"
                    ;;
                    "approvals set" | "exec-approvals set")
                        opts="--node --gateway --file --stdin --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --file --url --token --timeout"
                    ;;
                    "approvals allowlist" | "exec-approvals allowlist")
                        opts="add remove";
                        value_options="--container --profile --log-level"
                    ;;
                    "approvals allowlist add" | "exec-approvals allowlist add")
                        opts="--node --gateway --agent --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --agent --url --token --timeout"
                    ;;
                    "approvals allowlist remove" | "exec-approvals allowlist remove")
                        opts="--node --gateway --agent --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --agent --url --token --timeout"
                    ;;
                    "exec-policy")
                        opts="show preset set";
                        value_options="--container --profile --log-level"
                    ;;
                    "exec-policy show")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "exec-policy preset")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "exec-policy set")
                        opts="--host --security --ask --ask-fallback --json";
                        value_options="--container --profile --log-level --host --security --ask --ask-fallback"
                    ;;
                    "nodes")
                        opts="status describe list pending approve reject remove rename invoke notify push camera screen location canvas";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes status")
                        opts="--connected --last-connected --url --token --timeout --json";
                        value_options="--container --profile --log-level --last-connected --url --token --timeout"
                    ;;
                    "nodes describe")
                        opts="--node --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --url --token --timeout"
                    ;;
                    "nodes list")
                        opts="--connected --last-connected --url --token --timeout --json";
                        value_options="--container --profile --log-level --last-connected --url --token --timeout"
                    ;;
                    "nodes pending")
                        opts="--url --token --timeout --json";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "nodes approve")
                        opts="--url --token --timeout --json";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "nodes reject")
                        opts="--url --token --timeout --json";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "nodes remove")
                        opts="--node --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --url --token --timeout"
                    ;;
                    "nodes rename")
                        opts="--node --name --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --name --url --token --timeout"
                    ;;
                    "nodes invoke")
                        opts="--node --command --params --invoke-timeout --idempotency-key --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --command --params --invoke-timeout --idempotency-key --url --token --timeout"
                    ;;
                    "nodes notify")
                        opts="--node --title --body --sound --priority --delivery --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --title --body --sound --priority --delivery --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes push")
                        opts="--node --title --body --environment --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --title --body --environment --url --token --timeout"
                    ;;
                    "nodes camera")
                        opts="list snap clip";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes camera list")
                        opts="--node --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --url --token --timeout"
                    ;;
                    "nodes camera snap")
                        opts="--node --facing --device-id --max-width --quality --delay-ms --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --facing --device-id --max-width --quality --delay-ms --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes camera clip")
                        opts="--node --facing --device-id --duration --no-audio --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --facing --device-id --duration --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes screen")
                        opts="record";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes screen record")
                        opts="--node --screen --duration --fps --no-audio --out --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --screen --duration --fps --out --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes location")
                        opts="get";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes location get")
                        opts="--node --max-age --accuracy --location-timeout --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --max-age --accuracy --location-timeout --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas")
                        opts="snapshot present hide navigate eval a2ui";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes canvas snapshot")
                        opts="--node --format --max-width --quality --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --format --max-width --quality --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas present")
                        opts="--node --target --x --y --width --height --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --target --x --y --width --height --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas hide")
                        opts="--node --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas navigate")
                        opts="--node --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas eval")
                        opts="--js --node --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --js --node --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas a2ui")
                        opts="push reset";
                        value_options="--container --profile --log-level"
                    ;;
                    "nodes canvas a2ui push")
                        opts="--jsonl --text --node --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --jsonl --text --node --invoke-timeout --url --token --timeout"
                    ;;
                    "nodes canvas a2ui reset")
                        opts="--node --invoke-timeout --url --token --timeout --json";
                        value_options="--container --profile --log-level --node --invoke-timeout --url --token --timeout"
                    ;;
                    "devices")
                        opts="list remove clear approve reject rotate revoke";
                        value_options="--container --profile --log-level"
                    ;;
                    "devices list")
                        opts="--url --token --password --timeout --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "devices remove")
                        opts="--url --token --password --timeout --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "devices clear")
                        opts="--pending --yes --url --token --password --timeout --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "devices approve")
                        opts="--latest --url --token --password --timeout --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "devices reject")
                        opts="--url --token --password --timeout --json";
                        value_options="--container --profile --log-level --url --token --password --timeout"
                    ;;
                    "devices rotate")
                        opts="--device --role --scope --url --token --password --timeout --json";
                        value_options="--container --profile --log-level --device --role --scope --url --token --password --timeout"
                    ;;
                    "devices revoke")
                        opts="--device --role --url --token --password --timeout --json";
                        value_options="--container --profile --log-level --device --role --url --token --password --timeout"
                    ;;
                    "node")
                        opts="run status install uninstall stop start restart";
                        value_options="--container --profile --log-level"
                    ;;
                    "node run")
                        opts="--host --port --context-path --tls --tls-fingerprint --node-id --display-name";
                        value_options="--container --profile --log-level --host --port --context-path --tls-fingerprint --node-id --display-name"
                    ;;
                    "node status")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "node install")
                        opts="--host --port --context-path --tls --tls-fingerprint --node-id --display-name --runtime --force --json";
                        value_options="--container --profile --log-level --host --port --context-path --tls-fingerprint --node-id --display-name --runtime"
                    ;;
                    "node uninstall")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "node stop")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "node start")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "node restart")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "sandbox")
                        opts="list recreate explain";
                        value_options="--container --profile --log-level"
                    ;;
                    "sandbox list")
                        opts="--json --browser";
                        value_options="--container --profile --log-level"
                    ;;
                    "sandbox recreate")
                        opts="--all --session --agent --browser --force";
                        value_options="--container --profile --log-level --session --agent"
                    ;;
                    "sandbox explain")
                        opts="--session --agent --json";
                        value_options="--container --profile --log-level --session --agent"
                    ;;
                    "worktrees")
                        opts="list create remove restore gc";
                        value_options="--container --profile --log-level"
                    ;;
                    "worktrees list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "worktrees create")
                        opts="--name --base-ref --json";
                        value_options="--container --profile --log-level --name --base-ref"
                    ;;
                    "worktrees remove")
                        opts="--force --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "worktrees restore")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "worktrees gc")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "attach")
                        opts="--session --ttl --bin --print-config";
                        value_options="--container --profile --log-level --session --ttl --bin"
                    ;;
                    "tui" | "terminal" | "chat")
                        opts="--local --url --token --password --session --deliver --thinking --message --timeout-ms --history-limit";
                        value_options="--container --profile --log-level --url --token --password --session --thinking --message --timeout-ms --history-limit"
                    ;;
                    "cron")
                        opts="status list add create rm remove delete enable disable get show runs run edit";
                        value_options="--container --profile --log-level"
                    ;;
                    "cron status")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron list")
                        opts="--all --agent --json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --agent --url --token --timeout"
                    ;;
                    "cron add" | "cron create")
                        opts="--name --declaration-key --display-name --description --disabled --delete-after-run --keep-after-run --agent --session --session-key --wake --at --every --cron --on-exit --on-exit-cwd --tz --stagger --exact --trigger-script --trigger-once --system-event --message --command --command-argv --command-cwd --command-env --command-input --thinking --model --fallbacks --timeout-seconds --no-output-timeout-seconds --output-max-bytes --light-context --tools --announce --deliver --no-deliver --webhook --channel --to --thread-id --account --best-effort-deliver --json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --name --declaration-key --display-name --description --agent --session --session-key --wake --at --every --cron --on-exit --on-exit-cwd --tz --stagger --trigger-script -> --system-event --message --command --command-argv --command-cwd --command-env --command-input --thinking --model --fallbacks --timeout-seconds --no-output-timeout-seconds --output-max-bytes --tools --webhook --channel --to --thread-id --account --url --token --timeout"
                    ;;
                    "cron rm" | "cron remove" | "cron delete")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron enable")
                        opts="--url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron disable")
                        opts="--url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron get")
                        opts="--url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron show")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "cron runs")
                        opts="--id --run-id --limit --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --id --run-id --limit --url --token --timeout"
                    ;;
                    "cron run")
                        opts="--due --wait --wait-timeout --poll-interval --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --wait-timeout --poll-interval --url --token --timeout"
                    ;;
                    "cron edit")
                        opts="--name --description --enable --disable --delete-after-run --keep-after-run --session --agent --clear-agent --session-key --clear-session-key --wake --at --every --cron --tz --stagger --exact --trigger-script --trigger-once --clear-trigger --system-event --message --command --command-argv --command-cwd --command-env --command-input --thinking --clear-thinking --model --fallbacks --clear-fallbacks --clear-model --timeout-seconds --no-output-timeout-seconds --output-max-bytes --light-context --no-light-context --tools --clear-tools --announce --deliver --no-deliver --webhook --channel --to --thread-id --account --clear-channel --clear-to --clear-thread-id --clear-account --best-effort-deliver --no-best-effort-deliver --failure-alert --no-failure-alert --failure-alert-after --failure-alert-channel --failure-alert-to --failure-alert-cooldown --failure-alert-include-skipped --failure-alert-exclude-skipped --failure-alert-mode --failure-alert-account-id --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --name --description --session --agent --session-key --wake --at --every --cron --tz --stagger --trigger-script -> --system-event --message --command --command-argv --command-cwd --command-env --command-input --thinking --model --fallbacks --timeout-seconds --no-output-timeout-seconds --output-max-bytes --tools --webhook --channel --to --thread-id --account --failure-alert-after --failure-alert-channel --failure-alert-to --failure-alert-cooldown --failure-alert-mode --failure-alert-account-id --url --token --timeout"
                    ;;
                    "dns")
                        opts="setup";
                        value_options="--container --profile --log-level"
                    ;;
                    "dns setup")
                        opts="--domain --apply";
                        value_options="--container --profile --log-level --domain"
                    ;;
                    "docs")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "proxy")
                        opts="start run validate coverage sessions query blob purge";
                        value_options="--container --profile --log-level"
                    ;;
                    "proxy start")
                        opts="--host --port";
                        value_options="--container --profile --log-level --host --port"
                    ;;
                    "proxy run")
                        opts="--host --port";
                        value_options="--container --profile --log-level --host --port"
                    ;;
                    "proxy validate")
                        opts="--json --proxy-url --proxy-ca-file --allowed-url --denied-url --apns-reachable --apns-authority --timeout-ms";
                        value_options="--container --profile --log-level --proxy-url --proxy-ca-file --allowed-url --denied-url --apns-authority --timeout-ms"
                    ;;
                    "proxy coverage")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "proxy sessions")
                        opts="--limit";
                        value_options="--container --profile --log-level --limit"
                    ;;
                    "proxy query")
                        opts="--preset --session";
                        value_options="--container --profile --log-level --preset --session"
                    ;;
                    "proxy blob")
                        opts="--id";
                        value_options="--container --profile --log-level --id"
                    ;;
                    "proxy purge")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks")
                        opts="list info check enable disable relay install update";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks list")
                        opts="--eligible --json --verbose";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks info")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks check")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks enable")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks disable")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks relay")
                        opts="--provider --relay-id --generation --event --pre-tool-use-unavailable --timeout";
                        value_options="--container --profile --log-level --provider --relay-id --generation --event --pre-tool-use-unavailable --timeout"
                    ;;
                    "hooks install")
                        opts="--link --pin";
                        value_options="--container --profile --log-level"
                    ;;
                    "hooks update")
                        opts="--all --dry-run";
                        value_options="--container --profile --log-level"
                    ;;
                    "webhooks")
                        opts="gmail";
                        value_options="--container --profile --log-level"
                    ;;
                    "webhooks gmail")
                        opts="setup run";
                        value_options="--container --profile --log-level"
                    ;;
                    "webhooks gmail setup")
                        opts="--account --project --topic --subscription --label --hook-url --hook-token --push-token --bind --port --path --include-body --max-bytes --renew-minutes --tailscale --tailscale-path --tailscale-target --push-endpoint --json";
                        value_options="--container --profile --log-level --account --project --topic --subscription --label --hook-url --hook-token --push-token --bind --port --path --max-bytes --renew-minutes --tailscale --tailscale-path --tailscale-target --push-endpoint"
                    ;;
                    "webhooks gmail run")
                        opts="--account --topic --subscription --label --hook-url --hook-token --push-token --bind --port --path --include-body --max-bytes --renew-minutes --tailscale --tailscale-path --tailscale-target";
                        value_options="--container --profile --log-level --account --topic --subscription --label --hook-url --hook-token --push-token --bind --port --path --max-bytes --renew-minutes --tailscale --tailscale-path --tailscale-target"
                    ;;
                    "qr")
                        opts="--remote --url --public-url --token --password --setup-code-only --no-ascii --json";
                        value_options="--container --profile --log-level --url --public-url --token --password"
                    ;;
                    "clawbot")
                        opts="qr";
                        value_options="--container --profile --log-level"
                    ;;
                    "clawbot qr")
                        opts="--remote --url --public-url --token --password --setup-code-only --no-ascii --json";
                        value_options="--container --profile --log-level --url --public-url --token --password"
                    ;;
                    "pairing")
                        opts="list approve";
                        value_options="--container --profile --log-level"
                    ;;
                    "pairing list")
                        opts="--channel --account --json";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "pairing approve")
                        opts="--channel --account --notify";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "plugins")
                        opts="list search inspect info enable disable uninstall install update registry doctor build validate init marketplace";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins list")
                        opts="--json --enabled --verbose";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins search")
                        opts="--limit --json";
                        value_options="--container --profile --log-level --limit"
                    ;;
                    "plugins inspect" | "plugins info")
                        opts="--all --runtime --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins enable")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins disable")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins uninstall")
                        opts="--keep-files --keep-config --force --dry-run";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins install")
                        opts="--link --force --pin --dangerously-force-unsafe-install --acknowledge-clawhub-risk --marketplace";
                        value_options="--container --profile --log-level --marketplace"
                    ;;
                    "plugins update")
                        opts="--all --dry-run --dangerously-force-unsafe-install --acknowledge-clawhub-risk";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins registry")
                        opts="--json --refresh";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins doctor")
                        opts="";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins build")
                        opts="--root --entry --check";
                        value_options="--container --profile --log-level --root --entry"
                    ;;
                    "plugins validate")
                        opts="--root --entry";
                        value_options="--container --profile --log-level --root --entry"
                    ;;
                    "plugins init")
                        opts="--directory --name --type --force";
                        value_options="--container --profile --log-level --directory --name --type"
                    ;;
                    "plugins marketplace")
                        opts="entries refresh list";
                        value_options="--container --profile --log-level"
                    ;;
                    "plugins marketplace entries")
                        opts="--feed-profile --feed-url --offline --json";
                        value_options="--container --profile --log-level --feed-profile --feed-url"
                    ;;
                    "plugins marketplace refresh")
                        opts="--feed-profile --feed-url --expected-sha256 --json";
                        value_options="--container --profile --log-level --feed-profile --feed-url --expected-sha256"
                    ;;
                    "plugins marketplace list")
                        opts="--json";
                        value_options="--container --profile --log-level"
                    ;;
                    "channels")
                        opts="list status capabilities resolve logs add remove login logout";
                        value_options="--container --profile --log-level"
                    ;;
                    "channels list")
                        opts="--all --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "channels status")
                        opts="--channel --probe --timeout --json";
                        value_options="--container --profile --log-level --channel --timeout"
                    ;;
                    "channels capabilities")
                        opts="--channel --account --target --timeout --json";
                        value_options="--container --profile --log-level --channel --account --target --timeout"
                    ;;
                    "channels resolve")
                        opts="--channel --account --kind --json";
                        value_options="--container --profile --log-level --channel --account --kind"
                    ;;
                    "channels logs")
                        opts="--channel --lines --json";
                        value_options="--container --profile --log-level --channel --lines"
                    ;;
                    "channels add")
                        opts="--channel --account --name --token --token-file --secret --secret-file --bot-token --app-token --password --cli-path --url --base-url --http-url --auth-dir --use-env --db-path --service --region";
                        value_options="--container --profile --log-level --channel --account --name --token --token-file --secret --secret-file --bot-token --app-token --password --cli-path --url --base-url --http-url --auth-dir --db-path --service --region"
                    ;;
                    "channels remove")
                        opts="--channel --account --delete";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "channels login")
                        opts="--channel --account --verbose";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "channels logout")
                        opts="--channel --account";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "directory")
                        opts="self peers groups";
                        value_options="--container --profile --log-level"
                    ;;
                    "directory self")
                        opts="--channel --account --json";
                        value_options="--container --profile --log-level --channel --account"
                    ;;
                    "directory peers")
                        opts="list";
                        value_options="--container --profile --log-level"
                    ;;
                    "directory peers list")
                        opts="--channel --account --json --query --limit";
                        value_options="--container --profile --log-level --channel --account --query --limit"
                    ;;
                    "directory groups")
                        opts="list members";
                        value_options="--container --profile --log-level"
                    ;;
                    "directory groups list")
                        opts="--channel --account --json --query --limit";
                        value_options="--container --profile --log-level --channel --account --query --limit"
                    ;;
                    "directory groups members")
                        opts="--group-id --channel --account --json --limit";
                        value_options="--container --profile --log-level --group-id --channel --account --limit"
                    ;;
                    "security")
                        opts="audit";
                        value_options="--container --profile --log-level"
                    ;;
                    "security audit")
                        opts="--deep --auth --token --password --fix --json";
                        value_options="--container --profile --log-level --auth --token --password"
                    ;;
                    "secrets")
                        opts="reload audit configure apply";
                        value_options="--container --profile --log-level"
                    ;;
                    "secrets reload")
                        opts="--json --url --token --timeout --expect-final";
                        value_options="--container --profile --log-level --url --token --timeout"
                    ;;
                    "secrets audit")
                        opts="--check --allow-exec --json";
                        value_options="--container --profile --log-level"
                    ;;
                    "secrets configure")
                        opts="--apply --yes --providers-only --skip-provider-setup --agent --allow-exec --plan-out --json";
                        value_options="--container --profile --log-level --agent --plan-out"
                    ;;
                    "secrets apply")
                        opts="--from --dry-run --allow-exec --json";
                        value_options="--container --profile --log-level --from"
                    ;;
                    "skills")
                        opts="search install update verify curator workshop list info check --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills search")
                        opts="--limit --json";
                        value_options="--container --profile --log-level --agent --limit"
                    ;;
                    "skills install")
                        opts="--version --force --force-install --acknowledge-clawhub-risk --global --agent --as";
                        value_options="--container --profile --log-level --agent --version --as"
                    ;;
                    "skills update")
                        opts="--all --force-install --acknowledge-clawhub-risk --global --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills verify")
                        opts="--version --tag --card --global --agent";
                        value_options="--container --profile --log-level --agent --version --tag"
                    ;;
                    "skills curator")
                        opts="status pin unpin restore --json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills curator status")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills curator pin")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills curator unpin")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills curator restore")
                        opts="";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills workshop")
                        opts="list inspect propose-create propose-update revise apply reject quarantine --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills workshop list")
                        opts="--json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills workshop inspect")
                        opts="--json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills workshop propose-create")
                        opts="--name --description --proposal --proposal-dir --goal --evidence --json";
                        value_options="--container --profile --log-level --agent --name --description --proposal --proposal-dir --goal --evidence"
                    ;;
                    "skills workshop propose-update")
                        opts="--proposal --proposal-dir --description --goal --evidence --json";
                        value_options="--container --profile --log-level --agent --proposal --proposal-dir --description --goal --evidence"
                    ;;
                    "skills workshop revise")
                        opts="--proposal --proposal-dir --description --goal --evidence --json";
                        value_options="--container --profile --log-level --agent --proposal --proposal-dir --description --goal --evidence"
                    ;;
                    "skills workshop apply")
                        opts="--json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills workshop reject")
                        opts="--reason --json";
                        value_options="--container --profile --log-level --agent --reason"
                    ;;
                    "skills workshop quarantine")
                        opts="--reason --json";
                        value_options="--container --profile --log-level --agent --reason"
                    ;;
                    "skills list")
                        opts="--json --eligible --verbose --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills info")
                        opts="--json --agent";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "skills check")
                        opts="--agent --json";
                        value_options="--container --profile --log-level --agent"
                    ;;
                    "update")
                        opts="repair finalize wizard status --json --no-restart --dry-run --channel --tag --timeout --yes --acknowledge-clawhub-risk";
                        value_options="--container --profile --log-level --channel --tag --timeout"
                    ;;
                    "update repair")
                        opts="--json --channel --timeout --yes --acknowledge-clawhub-risk --no-restart";
                        value_options="--container --profile --log-level --channel --tag --timeout"
                    ;;
                    "update finalize")
                        opts="--json --channel --timeout --yes --acknowledge-clawhub-risk --no-restart";
                        value_options="--container --profile --log-level --channel --tag --timeout"
                    ;;
                    "update wizard")
                        opts="--timeout";
                        value_options="--container --profile --log-level --channel --tag --timeout"
                    ;;
                    "update status")
                        opts="--json --timeout";
                        value_options="--container --profile --log-level --channel --tag --timeout"
                    ;;
                esac
            ;;
        esac;
    done;
    COMPREPLY=($(compgen -W "${opts}" -- ${cur}))
}
command_not_found_handle () 
{ 
    if [ -x /usr/lib/command-not-found ]; then
        /usr/lib/command-not-found -- "$1";
        return $?;
    else
        if [ -x /usr/share/command-not-found/command-not-found ]; then
            /usr/share/command-not-found/command-not-found -- "$1";
            return $?;
        else
            printf "%s: command not found\n" "$1" 1>&2;
            return 127;
        fi;
    fi
}
export PATH='/usr/bin:/bin:/usr/local/bin:/root/.local/bin:/root/.npm-global/bin:/root/bin:/root/.nix-profile/bin:/root/.local/bin'