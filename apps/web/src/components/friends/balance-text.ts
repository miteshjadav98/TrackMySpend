import type { BalanceView } from "@moneymoney/contracts";

/** "Jaymin owes you ₹500.00" or "You owe Riya $10.00", for one currency's balance. */
export function balanceSentence(friendName: string, balance: BalanceView): string {
  return balance.amountMinor > 0
    ? `${friendName} owes you ${balance.formatted}`
    : `You owe ${friendName} ${balance.formatted}`;
}

/** Green when the friend owes the user, red when the user owes them. */
export function balanceTone(balance: BalanceView): string {
  return balance.amountMinor > 0 ? "text-income" : "text-danger";
}
