import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '@/api/client'

export interface LlmConfig {
  id: string
  name: string
  provider: string
  base_url: string
  model_name: string
  has_api_key: boolean
  is_default: boolean
  extra_params: Record<string, any>
  created_at: string
  updated_at: string
}

export interface ModelInfo {
  id: string
  owned_by: string
}

export const useLlmStore = defineStore('llm', () => {
  const configs = ref<LlmConfig[]>([])
  const models = ref<ModelInfo[]>([])
  const testing = ref(false)

  async function fetchConfigs() {
    configs.value = await request<LlmConfig[]>('/llm/configs')
  }

  /**
   * 从服务商拉模型列表（动态下拉）。
   * 传入临时 base_url/api_key；若为空则用已保存的默认配置。
   */
  async function fetchModels(
    baseUrlOrConfigId: string,
    apiKey?: string,
    isConfigId = false,
  ) {
    testing.value = true
    try {
      const body: Record<string, any> = isConfigId
        ? { config_id: baseUrlOrConfigId }
        : { base_url: baseUrlOrConfigId }
      if (apiKey) body.api_key = apiKey
      models.value = await request<ModelInfo[]>('/llm/models', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      return models.value
    } finally {
      testing.value = false
    }
  }

  /** 测试连接。返回 {ok, message, error_type} */
  async function testConnection(baseUrl: string, modelName: string, apiKey?: string) {
    testing.value = true
    try {
      return await request<{ ok: boolean; message: string; error_type: string | null }>(
        '/llm/test',
        {
          method: 'POST',
          body: JSON.stringify({ base_url: baseUrl, model_name: modelName, api_key: apiKey || undefined }),
        },
      )
    } finally {
      testing.value = false
    }
  }

  async function createConfig(data: {
    name: string
    base_url: string
    model_name: string
    api_key?: string
    is_default: boolean
  }) {
    const cfg = await request<LlmConfig>('/llm/configs', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    await fetchConfigs()
    return cfg
  }

  async function updateConfig(id: string, patch: Partial<LlmConfig> & { api_key?: string }) {
    const cfg = await request<LlmConfig>(`/llm/configs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
    await fetchConfigs()
    return cfg
  }

  async function deleteConfig(id: string) {
    await request(`/llm/configs/${id}`, { method: 'DELETE' })
    await fetchConfigs()
  }

  return {
    configs,
    models,
    testing,
    fetchConfigs,
    fetchModels,
    testConnection,
    createConfig,
    updateConfig,
    deleteConfig,
  }
})