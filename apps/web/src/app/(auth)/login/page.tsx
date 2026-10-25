import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";
import { AuthFrame } from "@/components/auth/auth-frame";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <AuthFrame>
      <Suspense>
        <AuthForm mode="login" />
      </Suspense>
    </AuthFrame>
  );
}
