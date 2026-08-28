"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { Alert, Button, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import {
  cancelSubscription,
  getBillingSummary,
  getUsageSummary,
  startCheckout,
} from "@/lib/billing-api";
import { getMyPermissions } from "@/lib/orgs-api";

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
};

function planLabel(plan: string): string {
  return PLAN_LABELS[plan] ?? plan;
}

export default function BillingPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const searchParams = useSearchParams();
  const checkoutResult = searchParams.get("checkout"); // "success" | "cancelled" | null
  const queryClient = useQueryClient();

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const canManage = permissionsQuery.data?.permissions.includes("billing:manage") ?? false;

  const billingQuery = useQuery({
    queryKey: ["billing", orgId, accessToken],
    queryFn: () => getBillingSummary(accessToken!, orgId),
    enabled: !!accessToken && canManage,
  });

  const usageQuery = useQuery({
    queryKey: ["usage", orgId, accessToken],
    queryFn: () => getUsageSummary(accessToken!, orgId),
    enabled: !!accessToken && canManage,
  });

  const checkoutMutation = useMutation({
    mutationFn: (plan: "pro" | "enterprise") => startCheckout(accessToken!, orgId, plan),
    onSuccess: (checkoutUrl) => {
      window.location.href = checkoutUrl;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelSubscription(accessToken!, orgId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["billing", orgId] });
    },
  });

  if (permissionsQuery.isSuccess && !canManage) {
    return (
      <>
        <h1 className="text-2xl font-semibold">Billing</h1>
        <Alert>Only the organization owner can view billing.</Alert>
      </>
    );
  }

  const billing = billingQuery.data;
  const usage = usageQuery.data;

  return (
    <>
      <h1 className="text-2xl font-semibold">Billing</h1>

      {checkoutResult === "success" && (
        <Alert data-testid="checkout-success">
          Checkout complete — your plan will update once Stripe confirms the subscription.
        </Alert>
      )}
      {checkoutResult === "cancelled" && (
        <Alert data-testid="checkout-cancelled">Checkout was cancelled.</Alert>
      )}

      {billingQuery.isLoading && <Spinner label="Loading billing…" />}
      {billingQuery.isError && (
        <Alert>
          {billingQuery.error instanceof Error ? billingQuery.error.message : "failed to load billing"}
        </Alert>
      )}
      {checkoutMutation.isError && (
        <Alert data-testid="checkout-error">
          {checkoutMutation.error instanceof Error
            ? checkoutMutation.error.message
            : "failed to start checkout"}
        </Alert>
      )}

      {billing && (
        <div className="flex w-full max-w-2xl flex-col gap-3 rounded border p-4">
          <h2 className="font-medium">Plan</h2>
          <p data-testid="current-plan" className="text-sm">
            {planLabel(billing.plan)} — status: {billing.status}
          </p>
          <p className="text-sm text-gray-600">
            Seats used: {billing.seats_used}
            {billing.seats_limit !== null ? ` / ${billing.seats_limit}` : " (unlimited)"}
          </p>
          <p className="text-sm text-gray-600">
            AI usage cap:{" "}
            {billing.monthly_cost_cap_usd !== null
              ? `$${billing.monthly_cost_cap_usd.toFixed(2)}/mo`
              : "unlimited"}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              onClick={() => checkoutMutation.mutate("pro")}
              disabled={billing.plan === "pro" || checkoutMutation.isPending}
              data-testid="upgrade-pro"
            >
              Upgrade to Pro
            </Button>
            <Button
              type="button"
              onClick={() => checkoutMutation.mutate("enterprise")}
              disabled={billing.plan === "enterprise" || checkoutMutation.isPending}
              data-testid="upgrade-enterprise"
            >
              Upgrade to Enterprise
            </Button>
            {billing.plan !== "free" && (
              <Button
                type="button"
                variant="danger"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                data-testid="cancel-subscription"
              >
                Cancel subscription
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex w-full max-w-2xl flex-col gap-3 rounded border p-4">
        <h2 className="font-medium">Usage this month{usage ? ` (${usage.month})` : ""}</h2>
        {usageQuery.isLoading && <Spinner label="Loading usage…" />}
        {usage && (
          <>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="py-2">Kind</th>
                  <th className="py-2">Tokens</th>
                  <th className="py-2">Cost</th>
                </tr>
              </thead>
              <tbody>
                {usage.items.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-2 text-gray-500">
                      No usage recorded yet this month.
                    </td>
                  </tr>
                )}
                {usage.items.map((item) => (
                  <tr key={item.kind} className="border-b">
                    <td className="py-2">{item.kind}</td>
                    <td className="py-2">{item.quantity}</td>
                    <td className="py-2">${item.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p data-testid="usage-total" className="text-sm text-gray-600">
              Total: ${usage.total_cost_usd.toFixed(4)}
              {usage.monthly_cost_cap_usd !== null && ` / $${usage.monthly_cost_cap_usd.toFixed(2)} cap`}
            </p>
          </>
        )}
      </div>
    </>
  );
}
