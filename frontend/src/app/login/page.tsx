"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { AuthProviderButton } from "@/components/auth-provider-button";
import { api } from "@/lib/api";
import { PageState } from "@/components/page-state";

export default function LoginPage() {
  const router = useRouter();
  const session = useQuery({ queryKey: ["session"], queryFn: api.getSession });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.getProviders });

  useEffect(() => {
    if (session.data?.authenticated) {
      router.replace("/inbox");
    }
  }, [router, session.data?.authenticated]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-xl rounded-4xl border border-white/80 bg-white/90 p-8 shadow-panel backdrop-blur-sm dark:border-slate-800 dark:bg-slate-950/90">
        <div className="text-xs uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Parallel Frontend</div>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900 dark:text-slate-50">מערכת אוטומציה להזמנות</h1>
        <p className="mt-4 text-slate-600 dark:text-slate-300">
          זהו הממשק החדש שפועל במקביל ל-Streamlit. ההתחברות נשמרת דרך ה-API החדש עם אותם ספקי OAuth וכללי הרשאה.
        </p>

        {providers.isLoading ? (
          <div className="mt-8 text-slate-600 dark:text-slate-300">טוען ספקי התחברות...</div>
        ) : providers.data && providers.data.length > 0 ? (
          <div className="mt-8 grid gap-3">
            {providers.data.map((provider) => (
              <AuthProviderButton
                key={provider.provider}
                href={api.loginUrl(provider.provider)}
                label={`התחבר באמצעות ${provider.label}`}
                provider={provider.provider}
              />
            ))}
          </div>
        ) : (
          <div className="mt-8">
            <PageState title="אין ספק התחברות פעיל" body="יש להגדיר OAuth ב-API לפני שימוש בממשק החדש." />
          </div>
        )}
      </div>
    </div>
  );
}
