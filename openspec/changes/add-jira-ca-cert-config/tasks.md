## 1. Implementation
- [ ] 1.1 Add optional `jira.ca_cert_path` to `config.yaml` and `config_prod.yaml` examples and document it in `README.md`.
- [ ] 1.2 Resolve `jira.ca_cert_path` in `config_manager.py` (relative to config file directory) and include it in `get_jira_config`.
- [ ] 1.3 Pass the CA cert path via `verify` in all JIRA HTTP calls (`jira_client.py`, `get_jira_parent.py`, `study_tools/jira_ticket_fetcher.py`).
- [ ] 1.4 Add minimal logging indicating whether a custom CA cert is in use (avoid logging the credential itself).

## 2. Validation
- [ ] 2.1 Run a JIRA connectivity check with `jira.ca_cert_path` set and confirm requests succeed.
- [ ] 2.2 Run the same check with `jira.ca_cert_path` omitted to confirm default TLS verification still works.
