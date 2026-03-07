# OAuth Sign-In Authentication Implementation (Google + Microsoft)

This document details the architecture, flow, and configuration for the OAuth sign-in system (Google and Microsoft) built into the Super Order Automation Dashboard.

## 1. Overview
The dashboard utilizes native OAuth 2.0/OpenID Connect flows to authenticate users via **Google** and **Microsoft**. It is implemented using standard `requests` instead of complex third-party wrappers, minimizing dependency overhead. The system also features:
- **Email Allowlist Authorization**: Only users explicitly defined in the environment variables are granted access to the dashboard.
- **Session Persistence**: Utilizes `streamlit-cookies-manager` to securely store a session cookie, preventing users from having to log in every time the app restarts or they open a new tab.
- **RTL Localization**: The login and error screens are fully translated and formatted (Right-To-Left) to match the Hebrew dashboard.

## 2. Core Components Modified/Created

### `src/dashboard/auth.py`
The primary module governing the entire authentication flow.
- **`get_login_url(provider=...)`**: Constructs a provider-specific authorize URL (Google/Microsoft) with required Client ID and redirection parameters.
- **`exchange_code_for_token(code, provider)`**: Exchanges the authorization `code` for the provider token payload.
- **`get_user_info(token_data, provider)`**: Fetches provider profile info and extracts normalized user identity.
- **`is_user_allowed(email)`**: Validates the extracted email against the central `ALLOWED_EMAILS` configuration.
- **`require_login()`**: The Streamlit interceptor function. It checks browser cookies and `st.session_state`. If the user is unauthenticated, it presents a provider selector (Google/Microsoft) and halts application rendering (`st.stop()`).

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
Authentication requires at least one configured provider in both `.env` (for local development) and standard Configuration properties (for Cloud Run):

- `GOOGLE_CLIENT_ID`: The OAuth 2.0 Client ID generated within GCP API & Credentials.
- `GOOGLE_CLIENT_SECRET`: The corresponding OAuth 2.0 Client Secret from GCP.
- `MICROSOFT_CLIENT_ID`: Azure App Registration application (client) ID.
- `MICROSOFT_CLIENT_SECRET`: Azure App Registration client secret.
- `MICROSOFT_TENANT_ID`: Azure tenant id for sign-in authority (`common` by default).
- `ALLOWED_EMAILS`: A comma-separated allowlist. Supports exact emails and domain suffix entries starting with `@` (e.g., `"admin@example.com,@superhome.co.il"`). (`ALLOWED_EMAILS_STR` is still accepted for backward compatibility.)
- `WEB_UI_URL`: The active callback URI for the OAuth sequence in Production. (e.g., `https://order-dashboard-xyz.run.app`)
- `COOKIE_SECRET`: Recommended dedicated signing key for auth cookie/state signatures.

### Smart URL Resolution (`get_web_ui_url`)
To prevent developers from needing to manually comment/uncomment the `WEB_UI_URL` variable between testing environments, `src/shared/config.py` uses a property named `get_web_ui_url`.
- If the application detects it is running in **Cloud Run** (`is_cloud_runtime = True`), it utilizes the `WEB_UI_URL` from the environment.
- If it detects it is running **Locally**, it safely ignores the environment block and defaults to `http://localhost:8501/`.

> **Note on Redirections**: Ensure both `http://localhost:8501/` and the production URL are registered in each provider console (Google OAuth client and Azure App Registration redirect URIs).

## 4. Troubleshooting and Edge Cases

### Cookies and Rerun Race Conditions
A critical challenge addressed was the Streamlit lifecycle wiping out login states across browser refreshes. Streamlit does not inherently remember session tokens across script reruns or closures.
- **The Fix**: The system stores a signed `auth_session` cookie (email, display name, provider, timestamps, signature) via `streamlit-cookies-manager`.
- **The Delay Hack**: When logging out or saving a freshly acquired cookie, the browser's JavaScript needs a fraction of a second to physically commit the cookie back to the local storage before Streamlit attempts to rerender. Therefore, the auth module occasionally initiates an intentional `time.sleep(1)` delay (or simply `return` statements instead of forcing `st.rerun()`) so cookie synchronization processes cleanly.

### OAuth Callback Integrity (`state`)
To protect against callback tampering / CSRF-style OAuth issues, the flow now:
- Generates a per-login nonce and sends it in OAuth `state`.
- Validates the nonce on callback before exchanging the `code`.
- Preserves `?session=<id>` deep links through the callback via state payload so emailed edit links continue to work after login.

### Accidental RTL Unstyling
If the "Access Denied" or Login UI suddenly displays Left-To-Right with broken fonts:
- Make sure `load_css(css_path)` executes at the top of `app.py`, immediately **above** the `auth.require_login()` interceptor. Reversing the placement causes `st.stop()` to trigger early blocking the CSS loader.
