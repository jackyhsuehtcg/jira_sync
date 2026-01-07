# run-cleanup Specification

## Purpose
TBD - created by archiving change add-cleanup-timeout-logging. Update Purpose after archive.
## Requirements
### Requirement: Cleanup lifecycle logging
The system SHALL emit monitor-visible log entries when cleanup starts, is running, and finishes (success or failure), including the DataCleaner phase invoked by daily cleanup.

#### Scenario: Daily cleanup runs
- **WHEN** daily cleanup triggers
- **THEN** the monitor log includes a cleanup start entry
- **AND** the monitor log includes a data_cleaner running entry
- **AND** the monitor log includes a cleanup finished entry with success or failure

### Requirement: Global cleanup status display
The system SHALL display cleanup status across all table rows in the monitor UI while daily cleanup is running.

#### Scenario: Cleanup status is visible globally
- **WHEN** daily cleanup is running
- **THEN** every table row shows a cleanup-in-progress status indicator

### Requirement: Cleanup timeout
The system SHALL enforce a 120-minute timeout for the daily cleanup process (table_scan_cleaner) and terminate it if exceeded, then resume sync.

#### Scenario: Cleanup exceeds timeout
- **WHEN** the cleanup process runs longer than 120 minutes
- **THEN** the process is terminated
- **AND** the monitor log records a timeout event
- **AND** sync resumes for all tables

