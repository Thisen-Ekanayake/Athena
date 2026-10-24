import { apiClient } from './client'

/** Hands a file to the browser to save. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Downloads a file from the API with the session cookie and saves it. A failed download's body is a Blob too, so
 * the server's message is read out of it for the error.
 */
export async function downloadFile(path: string, params: Record<string, string>, filename: string) {
  try {
    const resp = await apiClient.get<Blob>(path, { params, responseType: 'blob' })
    saveBlob(resp.data, filename)
  } catch (e) {
    const data = (e as { response?: { data?: unknown } })?.response?.data
    if (data instanceof Blob) {
      let detail: string | undefined
      try {
        detail = (JSON.parse(await data.text()) as { detail?: string }).detail
      } catch {
        // not JSON: fall back to axios's message
      }
      if (detail) throw new Error(detail, { cause: e })
    }
    throw e
  }
}
