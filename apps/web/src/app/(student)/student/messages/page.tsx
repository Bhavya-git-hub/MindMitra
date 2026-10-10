import type { Metadata } from "next";

import { MessagesView } from "@/components/student/messages-views";

export const metadata: Metadata = { title: "Messages" };

export default function Page() {
  return <MessagesView />;
}
