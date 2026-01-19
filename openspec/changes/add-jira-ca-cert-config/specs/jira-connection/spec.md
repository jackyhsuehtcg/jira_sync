## ADDED Requirements
### Requirement: Configurable JIRA CA certificate
The system SHALL allow configuring a CA certificate path for JIRA HTTPS connections and use it for TLS verification on all JIRA API requests.

#### Scenario: Custom CA certificate configured
- **WHEN** jira.ca_cert_path is configured
- **THEN** all JIRA HTTPS requests use that certificate for TLS verification

#### Scenario: No custom CA certificate configured
- **WHEN** jira.ca_cert_path is not configured
- **THEN** JIRA HTTPS requests use the default TLS verification behavior

### Requirement: Resolve JIRA CA certificate path
The system SHALL resolve a non-absolute jira.ca_cert_path relative to the config file directory.

#### Scenario: Relative path provided
- **WHEN** jira.ca_cert_path is a relative path
- **THEN** the system resolves it relative to the config file directory before use
