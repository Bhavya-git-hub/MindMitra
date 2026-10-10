import type { Metadata } from "next";

import { ProfileView } from "@/components/therapist/profile-view";

export const metadata: Metadata = { title: "Profile" };

export default function Page() {
  return <ProfileView />;
}
