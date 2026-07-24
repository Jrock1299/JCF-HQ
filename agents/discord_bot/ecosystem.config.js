// pm2 process definition for the JCF HQ two-way Discord bot.
//   pm2 start  agents/discord_bot/ecosystem.config.js
//   pm2 restart jcf-discord-bot     # after granting Manage Webhooks / setting webhook URLs
//   pm2 logs    jcf-discord-bot
//   pm2 save                        # persist across reboots
//
// run_bot.sh sources /root/.openclaw/.env and execs the openclaw venv python,
// so no env injection is needed here.
module.exports = {
  apps: [
    {
      name: 'jcf-discord-bot',
      script: '/root/.openclaw/agents/discord_bot/run_bot.sh',
      interpreter: 'bash',
      cwd: '/root/.openclaw',
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      out_file: '/root/.openclaw/logs/discord_bot.log',
      error_file: '/root/.openclaw/logs/discord_bot.err.log',
      merge_logs: true,
      time: true,
    },
  ],
};
