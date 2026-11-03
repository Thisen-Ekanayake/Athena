/** How an MCP client reaches Athena. The server sits on the app's own origin: Vite and nginx pass /mcp to the API,
 *  as they pass /api. */
export const mcpUrl = () => `${window.location.origin}/mcp`

export const claudeCommand = (token: string) =>
  `claude mcp add --transport http athena ${mcpUrl()} --header "Authorization: Bearer ${token}"`

export const clientConfig = (token: string) =>
  JSON.stringify({ mcpServers: { athena: { type: 'http', url: mcpUrl(), headers: { Authorization: `Bearer ${token}` } } } }, null, 2)
