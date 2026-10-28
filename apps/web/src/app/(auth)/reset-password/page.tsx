import type { Metadata } from "next";

import { AuthFrame } from "@/components/auth/auth-frame";
import { ResetPasswordForm } from "@/components/auth/password-reset";

export const metadata: Metadata = {
  title: "Reset password",
  // The reset token is in the URL fragment, which is never sent, but leave nothing to chance.
  referrer: "no-referrer",
};

export default function ResetPasswordPage() {
  return (
    <AuthFrame>
      <ResetPasswordForm />
    </AuthFrame>
  );
}
