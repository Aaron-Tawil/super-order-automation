# Google Sign-In Authentication Implementation

This document details the architecture, flow, and configuration for the Google Sign-In authentication system built into the Super Order Automation Dashboard.

## 1. Overview
The dashboard utilizes a native Google OAuth 2.0 flow to authenticate users. It is implemented using standard `requests` instead of complex third-party wrappers, minimizing dependency overhead. The system also features:
- **Email Allowlist Authorization**: Only users explicitly defined in the environment variables are granted access to the dashboard.
- **Session Persistence**: Utilizes `streamlit-cookies-manager` to securely store a session cookie, preventing users from having to log in every time the app restarts or they open a new tab.
- **RTL Localization**: The login and error screens are fully translated and formatted (Right-To-Left) to match the Hebrew dashboard.

## 2. Core Components Modified/Created

### `src/dashboard/auth.py`
The primary module governing the entire authentication flow.
- **`get_login_url()`**: Constructs the authorize URL (pointing to `accounts.google.com/o/oauth2/auth`) with the required Google Client ID and Redirection parameters.
- **`exchange_code_for_token(code)`**: Once the user authenticates, Google redirects back to the dashboard with an authorization `code`. This function exchanges that code for an access token.
- **`get_user_info(token)`**: Fetches Google profile info and extracts the authenticated user's email address.
- **`is_user_allowed(email)`**: Validates the extracted email against the central `ALLOWED_EMAILS` configuration.
- **`require_login()`**: The Streamlit interceptor function. It checks the browser's cookies and `st.session_state`. If the user is unauthenticated, it presents the login screen and instantly halts the application (`st.stop()`) to block the dashboard content.

### `src/dashboard/app.py`
The main Streamlit entry point.
- **Global CSS Loading**: Ensures `styles.css` is loaded *before* authentication. This guarantees that if a user hits an "Access Denied" or "Login" screen, the page still inherits the correct Right-To-Left formatting.
- **Middleware Integration**: `auth.require_login()` is invoked near the top of the script.
- **Logout Action**: Provides a logout button (`auth.logout()`) at the top of the sidebar alongside the signed-in user's email indication.

### `src/dashboard/__init__.py`
An empty file was created in the `dashboard` directory. This turns the directory into a valid Python package, safely preventing `ImportError` exceptions when Streamlit's auto-reloader detects changes.

### `src/shared/config.py`
Updated to seamlessly parse new authentication environment variables into the central `settings` object.

### `src/shared/translations.py`
Added a new `# --- Authentication ---` section containing all dynamic Hebrew strings for login buttons, error messages, and sidebar components, utilizing the `get_text()` centralized translation system.

### `deploy_ui.py`
Modified the Cloud Run deployment script to read the new Google OAuth configurations and inject them into the Docker container via `env_vars.yaml`.

---

## 3. Environment Dependencies
Authentication strictly requires the following Environment Variables in both `.env` (for local development) and standard Configuration properties (for Cloud Run):

- `GOOGLE_CLIENT_ID`: The OAuth 2.0 Client ID generated within GCP API & Credentials.
- `GOOGLE_CLIENT_SECRET`: The corresponding OAuth 2.0 Client Secret from GCP.
- `ALLOWED_EMAILS`: A comma-separated string of email addresses permitted to use the dashboard (e.g., `"admin@example.com,user@example.com"`). (`ALLOWED_EMAILS_STR` is still accepted for backward compatibility.)
- `WEB_UI_URL`: The active callback URI for the OAuth sequence in Production. (e.g., `https://order-dashboard-xyz.run.app`)

### Smart URL Resolution (`get_web_ui_url`)
To prevent developers from needing to manually comment/uncomment the `WEB_UI_URL` variable between testing environments, `src/shared/config.py` uses a property named `get_web_ui_url`.
- If the application detects it is running in **Cloud Run** (`is_cloud_runtime = True`), it utilizes the `WEB_UI_URL` from the environment.
- If it detects it is running **Locally**, it safely ignores the environment block and defaults to `http://localhost:8501/`.

> **Note on Redirections**: Ensure both `http://localhost:8501/` and the Production URL are formally registered under "Authorized redirect URIs" within the Google Cloud Console's OAuth Client settings.

## 4. Troubleshooting and Edge Cases

### Cookies and Rerun Race Conditions
A critical challenge addressed was the Streamlit lifecycle wiping out login states across browser refreshes. Streamlit does not inherently remember session tokens across script reruns or closures.
- **The Fix**: The system securely encrypts and stores the logged-in email into browser cookies via `streamlit-cookies-manager`. 
- **The Delay Hack**: When logging out or saving a freshly acquired cookie, the browser's JavaScript needs a fraction of a second to physically commit the cookie back to the local storage before Streamlit attempts to rerender. Therefore, the auth module occasionally initiates an intentional `time.sleep(1)` delay (or simply `return` statements instead of forcing `st.rerun()`) so cookie synchronization processes cleanly.

### OAuth Callback Integrity (`state`)
To protect against callback tampering / CSRF-style OAuth issues, the flow now:
- Generates a per-login nonce and sends it in OAuth `state`.
- Validates the nonce on callback before exchanging the `code`.
- Preserves `?session=<id>` deep links through the callback via state payload so emailed edit links continue to work after login.

### Accidental RTL Unstyling
If the "Access Denied" or the Login UI suddenly displays Left-To-Right with broken fonts:
- Make sure `load_css(css_path)` executes at the top of `app.py`, immediately **above** the `auth.require_login()` interceptor. Reversing the placement causes `st.stop()` to trigger early blocking the CSS loader.
