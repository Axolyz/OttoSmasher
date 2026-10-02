export async function readApiResponse(response: Response, url: string) {
  const text = await response.text();
  let data: any;
  try { data = JSON.parse(text); }
  catch {
    throw Error(response.ok
      ? `接口返回格式异常：${url}`
      : `请求失败（HTTP ${response.status}）：${url}。请查看 data/logs/desktop-service.log；更新代码后可重新运行启动脚本。`);
  }
  if (!response.ok) {
    const detail = data?.detail;
    throw Error(typeof detail === "string" ? detail : detail
      ? JSON.stringify(detail) : `请求失败（HTTP ${response.status}）：${url}`);
  }
  return data;
}
