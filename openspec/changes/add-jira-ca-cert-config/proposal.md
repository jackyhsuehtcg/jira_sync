# Change: Add configurable JIRA CA certificate path

## Why
JIRA requires a specific CA certificate for TLS verification, and the sync should use a configurable CA bundle across all JIRA calls.

## What Changes
- Add optional `jira.ca_cert_path` in config.yaml for the CA certificate path.
- Use the configured CA certificate for TLS verification in all JIRA HTTP requests.
- Resolve relative paths against the config file directory.
- Document the new setting.

## Impact
- Affected specs: jira-connection (new)
- Affected code: jira_client.py, get_jira_parent.py, study_tools/jira_ticket_fetcher.py, config_manager.py, config.yaml, config_prod.yaml, README.md
