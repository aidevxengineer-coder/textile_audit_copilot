import { ChatWorkbench } from "@/components/chat/chat-workbench";
import { getServerProjects, getServerSessions, requireServerUser } from "@/lib/server-api";

export default async function ChatPage() {
  const [user, projects, sessions] = await Promise.all([requireServerUser(), getServerProjects(), getServerSessions()]);

  return <ChatWorkbench initialUser={user} initialProjects={projects} initialSessions={sessions} />;
}
