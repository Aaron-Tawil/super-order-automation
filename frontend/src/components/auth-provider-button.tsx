type Provider = "google" | "microsoft";

function GoogleIcon() {
  return (
    <svg className="size-5" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.5 3.9-5.5 3.9-3.3 0-6-2.7-6-6s2.7-6 6-6c1.9 0 3.1.8 3.8 1.4l2.6-2.5C16.7 3.4 14.6 2.5 12 2.5A9.5 9.5 0 1 0 12 21.5c5.5 0 9.1-3.8 9.1-9.2 0-.6-.1-1.1-.2-1.6z" />
      <path fill="#34A853" d="M4.3 7.9 7.5 10c.9-2.6 3.4-4.5 6.5-4.5 1.9 0 3.6.7 4.8 1.9l2.8-2.7C19.7 2.9 17 2 14 2 10.2 2 6.8 4.2 5.1 7.3z" />
      <path fill="#FBBC05" d="M4.8 12c0-.8.1-1.4.3-2.1L1.9 7.5A9.2 9.2 0 0 0 1 12c0 1.6.4 3.2 1 4.5l3.2-2.5c-.2-.6-.4-1.3-.4-2z" />
      <path fill="#4285F4" d="M12 21.5c2.6 0 4.7-.9 6.3-2.4l-3-2.5c-.8.6-1.9 1-3.3 1-3 0-5.5-1.9-6.4-4.6l-3.2 2.5C4.1 19 7.7 21.5 12 21.5z" />
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg className="size-5" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="3" width="8" height="8" fill="#F25022" />
      <rect x="13" y="3" width="8" height="8" fill="#7FBA00" />
      <rect x="3" y="13" width="8" height="8" fill="#00A4EF" />
      <rect x="13" y="13" width="8" height="8" fill="#FFB900" />
    </svg>
  );
}

export function AuthProviderButton({
  href,
  provider,
  label,
}: {
  href: string;
  provider: Provider;
  label: string;
}) {
  const icon = provider === "google" ? <GoogleIcon /> : <MicrosoftIcon />;

  return (
    <a
      className="flex items-center justify-center gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 text-center text-slate-900 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
      href={href}
    >
      {icon}
      <span>{label}</span>
    </a>
  );
}
