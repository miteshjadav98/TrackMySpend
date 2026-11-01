import { AccountsSection } from "@/components/settings/accounts-section";
import { AppearanceSection } from "@/components/settings/appearance-section";
import { MerchantRulesSection } from "@/components/settings/merchant-rules-section";
import { ProfileSection } from "@/components/settings/profile-section";
import { SecuritySection } from "@/components/settings/security-section";

/**
 * The settings page: a stack of independent sections, in the order they appear.
 *
 * Each section is its own file that wraps its content in `SettingsSection` and loads its own
 * data. To add one (Accounts, Merchant rules, Security), write `<name>-section.tsx` and add
 * one line below.
 */
export function SettingsScreen() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-xl px-4 py-6 md:px-8">
        <h1 className="display text-[1.9rem] leading-tight font-semibold">Settings</h1>
        <div className="mt-8 flex flex-col gap-10">
          <ProfileSection />
          <AppearanceSection />
          <AccountsSection />
          <MerchantRulesSection />
          <SecuritySection />
        </div>
      </div>
    </div>
  );
}
