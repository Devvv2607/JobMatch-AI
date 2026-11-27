import type { Metadata } from "next";

import { Onboarding } from "@/components/onboarding/onboarding-flow";

export const metadata: Metadata = { title: "Set up your profile · JobMatch" };

export default function OnboardingPage() {
  return <Onboarding />;
}
