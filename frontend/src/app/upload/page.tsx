"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { AppShell } from "@/components/app-shell";
import { api } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [isTest, setIsTest] = useState(false);

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("No file selected");
      const formData = new FormData();
      formData.append("file", file);
      formData.append("is_test", String(isTest));
      return api.extractUpload(formData);
    },
    onSuccess: (result) => router.push(`/orders/${result.order_id}`),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl rounded-4xl border border-white/70 bg-white/90 p-6 shadow-panel">
        <h2 className="text-2xl font-semibold text-slate-900">העלאה ידנית</h2>
        <p className="mt-2 text-sm text-slate-600">העלה PDF או Excel, הרץ את צינור החילוץ החדש, ועבור ישר להזמנה שנשמרה.</p>

        <div className="mt-6 grid gap-4">
          <label className="grid gap-2 text-sm text-slate-700">
            קובץ
            <input
              accept=".pdf,.xlsx,.xls"
              className="rounded-2xl border border-slate-200 px-4 py-3"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              type="file"
            />
          </label>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input checked={isTest} onChange={(event) => setIsTest(event.target.checked)} type="checkbox" />
            סמן כהזמנת טסט
          </label>

          <button
            className="rounded-2xl bg-slate-950 px-5 py-3 text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            disabled={!file || upload.isPending}
            onClick={() => upload.mutate()}
            type="button"
          >
            {upload.isPending ? "מעבד..." : "חלץ נתונים"}
          </button>

          {upload.isError ? <div className="text-sm text-rose-700">{String(upload.error)}</div> : null}
        </div>
      </div>
    </AppShell>
  );
}
