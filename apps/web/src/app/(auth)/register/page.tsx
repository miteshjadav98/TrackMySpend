import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";
import { AuthFrame } from "@/components/auth/auth-frame";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <AuthFrame>
      <Suspense>
        <AuthForm mode="register" />
      </Suspense>
    </AuthFrame>
  );
}
