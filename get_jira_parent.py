
import requests
import yaml
import json

def get_jira_issue_parent(issue_key):
    """
    Fetches the parent information for a given JIRA issue.

    Args:
        issue_key (str): The JIRA issue key (e.g., "TCG-108387").

    Returns:
        dict: The parent issue information, or None if not found or an error occurs.
    """
    try:
        # Load JIRA config from config.yaml
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        jira_config = config.get('jira', {})
        server_url = jira_config.get('server_url')
        username = jira_config.get('username')
        password = jira_config.get('password')

        if not all([server_url, username, password]):
            print("Error: JIRA configuration (server_url, username, password) is missing in config.yaml")
            return None

        # Construct the API URL
        api_url = f"{server_url.rstrip('/')}/rest/api/2/issue/{issue_key}?fields=parent"

        # Set up authentication
        auth = (username, password)

        # Make the request
        response = requests.get(api_url, auth=auth, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Parse the JSON response
        issue_data = response.json()
        parent_info = issue_data.get('fields', {}).get('parent')

        return parent_info

    except FileNotFoundError:
        print("Error: config.yaml not found.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from JIRA: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

if __name__ == "__main__":
    issue_key = "TCG-108387"
    parent = get_jira_issue_parent(issue_key)
    
    if parent:
        print(json.dumps(parent, indent=2))
    else:
        print(f"Could not retrieve parent information for {issue_key}.")

