# 智能部署系统设计 - 真正的运维智能体

## 核心理念

**不是硬编码解决方案，而是智能决策系统**

### ❌ 传统做法（硬编码）
```
遇到 SECRET_KEY 缺失 → 总是用 openssl 生成
遇到命令拦截 → 直接失败
遇到端口占用 → 换固定端口
```

### ✅ 智能体做法（自适应）
```
遇到 SECRET_KEY 缺失 
  → 分析项目类型
  → 评估多种方案（openssl、从模板复制、手动配置）
  → 根据环境选择最优方案
  → 如果无法自动解决 → 引导用户配置

遇到命令拦截
  → 识别拦截原因
  → 自动尝试替代命令
  → 如果无替代方案 → 明确说明原因，提供手动步骤

遇到端口占用
  → 检测可用端口
  → 询问用户偏好
  → 或自动选择最佳端口
```

---

## 设计框架

### 1. 多策略决策系统

```python
class DeployStrategy:
    """部署策略基类"""
    
    def evaluate(self, context: ProjectContext) -> float:
        """评估策略可行性 (0-1)"""
        pass
    
    def execute(self, context: ProjectContext) -> Result:
        """执行策略"""
        pass
    
    def fallback_message(self) -> str:
        """失败时的用户引导"""
        pass


class EnvironmentVariableStrategy:
    """环境变量处理策略"""
    
    strategies = [
        GenerateWithOpensslStrategy(),      # 优先级1：使用 openssl
        CopyFromExampleStrategy(),          # 优先级2：从 .env.example 复制
        UseDefaultValueStrategy(),          # 优先级3：使用默认值
        AskUserStrategy(),                  # 优先级4：询问用户
    ]
    
    def solve(self, var_name: str, context: ProjectContext):
        for strategy in self.strategies:
            if strategy.evaluate(context) > 0.7:  # 可行性阈值
                result = strategy.execute(context)
                if result.success:
                    return result
        
        # 所有策略都失败 → 引导用户
        return self._guide_user(var_name, context)
```

### 2. 命令拦截智能重试

```python
class CommandBlockHandler:
    """命令拦截处理器"""
    
    def handle_blocked_command(
        self,
        command: str,
        block_reason: str,
        context: ProjectContext
    ) -> CommandResult:
        """
        智能处理被拦截的命令
        
        步骤：
        1. 分析拦截原因（分号、管道、重定向等）
        2. 尝试等价替代命令
        3. 如果无替代方案，生成用户指引
        """
        
        if "';'" in block_reason:
            # 情况：Python 命令包含分号
            return self._try_alternatives([
                # 策略1：使用 openssl 替代
                AlternativeCommand(
                    original="python -c 'import secrets; ...'",
                    alternative="openssl rand -hex 32",
                    reason="openssl 无需分号，更安全"
                ),
                # 策略2：分步执行
                AlternativeCommand(
                    original="...",
                    alternative=["生成到临时文件", "读取文件内容"],
                    reason="分步执行避免复杂语法"
                ),
                # 策略3：引导用户手动操作
                UserGuidance(
                    message="无法自动生成密钥，请手动执行：",
                    steps=[
                        "1. 运行：python -c 'import secrets; print(secrets.token_hex(32))'",
                        "2. 复制输出到 .env 文件：SECRET_KEY=<生成的值>",
                        "3. 重新部署"
                    ]
                )
            ])
```

### 3. 项目适应性分析

```python
class ProjectAnalyzer:
    """项目特征分析器"""
    
    def analyze(self, project_path: str) -> ProjectProfile:
        """
        深度分析项目特征
        
        分析维度：
        - 技术栈（语言、框架）
        - 依赖关系
        - 配置复杂度
        - 环境要求
        - 常见问题
        """
        
        return ProjectProfile(
            type="docker-python-flask",
            complexity="medium",
            required_env_vars=[
                EnvVar(
                    name="SECRET_KEY",
                    type="secret",
                    can_auto_generate=True,
                    generation_methods=["openssl", "python"],
                ),
                EnvVar(
                    name="DATABASE_URL",
                    type="config",
                    can_auto_generate=False,
                    requires_user_input=True,
                    default_value="sqlite:///app.db",
                )
            ],
            known_issues=[
                "Flask SECRET_KEY 缺失会导致容器启动失败",
                "端口 5000 可能被其他应用占用"
            ]
        )
```

### 4. 用户交互引导系统

```python
class UserGuidance:
    """用户引导系统"""
    
    def guide_configuration(
        self,
        issue: DeploymentIssue,
        context: ProjectContext
    ) -> UserPrompt:
        """
        生成清晰的用户配置指引
        
        输出格式：
        - 问题描述
        - 可选方案
        - 每个方案的步骤
        - 推荐方案（带理由）
        """
        
        return UserPrompt(
            title="❌ 部署失败：缺少必需环境变量 SECRET_KEY",
            description=(
                "项目需要 SECRET_KEY 环境变量，但未找到配置。"
                "这是 Flask 应用的安全密钥，用于会话管理。"
            ),
            options=[
                Option(
                    label="方案 1：自动生成（推荐）",
                    steps=[
                        "智能体将使用 openssl 生成随机密钥",
                        "自动创建 .env 文件",
                        "重新启动容器"
                    ],
                    action="auto_generate",
                    recommended=True,
                    reason="最快速，适合测试环境"
                ),
                Option(
                    label="方案 2：使用已有密钥",
                    steps=[
                        "请提供您的 SECRET_KEY",
                        "智能体将创建 .env 文件",
                        "重新启动容器"
                    ],
                    action="ask_user_input",
                    recommended=False,
                    reason="适合生产环境，使用固定密钥"
                ),
                Option(
                    label="方案 3：手动配置",
                    steps=[
                        "1. 在项目目录创建 .env 文件",
                        "2. 添加：SECRET_KEY=your-secret-key-here",
                        "3. 重新运行部署命令"
                    ],
                    action="manual",
                    recommended=False,
                    reason="完全控制配置"
                )
            ],
            auto_select_after=10,  # 10秒后自动选择推荐方案
        )
```

---

## 实施计划

### Phase 1: 命令拦截智能重试（立即实施）

**目标**：解决 outlookEmail 的 SECRET_KEY 生成问题

**实现**：
1. 在 `diagnose.py` 中添加 `CommandBlockHandler`
2. 检测到命令被拦截时，自动尝试替代方案
3. 记录尝试过的方案，避免循环

**代码位置**：`src/workers/deploy/diagnose.py`

```python
async def handle_blocked_command(
    self,
    command: str,
    block_reason: str
) -> tuple[bool, str, list[str], Optional[str]]:
    """处理被拦截的命令"""
    
    # 检测是否是 Python 分号问题
    if "';'" in command and "secrets" in command:
        # 尝试 openssl 替代
        alternative = "openssl rand -hex 32"
        self._report_progress(
            "deploy",
            f"    ⚠️ 原命令被拦截，尝试替代方案：{alternative}"
        )
        return True, "使用 openssl 替代 Python", [], alternative
    
    # 其他拦截情况...
    return False, "无法自动解决命令拦截", [], None
```

### Phase 2: 多策略环境变量处理（1-2天）

**目标**：支持多种环境变量生成方式

**实现**：
1. 创建 `src/workers/deploy/strategies.py`
2. 实现多种策略：openssl、.env.example、默认值、询问用户
3. 根据项目特征自动选择最优策略

### Phase 3: 项目适应性分析（3-5天）

**目标**：根据项目类型调整部署策略

**实现**：
1. 分析 README、配置文件、代码注释
2. 识别常见问题和最佳实践
3. 生成项目特定的部署建议

### Phase 4: 用户交互系统（1周）

**目标**：当无法自动解决时，提供清晰的用户引导

**实现**：
1. 设计统一的用户提示格式
2. 实现选项菜单（CLI 和 TUI）
3. 支持超时自动选择推荐方案

---

## 测试场景

### 场景 1：outlookEmail（当前问题）
```
输入：部署 outlookEmail
问题：缺少 SECRET_KEY，Python 命令被拦截
智能体行为：
  1. 识别 SECRET_KEY 缺失
  2. 尝试 Python 命令 → 被拦截
  3. 自动切换到 openssl
  4. 成功生成并部署
```

### 场景 2：需要数据库配置的项目
```
输入：部署一个需要 DATABASE_URL 的项目
问题：无法自动生成数据库连接
智能体行为：
  1. 识别 DATABASE_URL 是配置类变量
  2. 检查 .env.example 是否有默认值
  3. 如果有 → 使用默认值（如 sqlite）
  4. 如果没有 → 询问用户提供
```

### 场景 3：复杂的多服务项目
```
输入：部署 docker-compose 项目（前端+后端+数据库）
问题：多个服务，多个环境变量，端口冲突
智能体行为：
  1. 分析 docker-compose.yml
  2. 逐个检查服务的配置
  3. 自动解决可解决的（如生成密钥）
  4. 对于需要用户决策的（如数据库密码），提供选项菜单
  5. 一次性收集所有配置，避免多次打断用户
```

---

## 实施顺序

### 🚀 立即实施（今天）
**Phase 1: 命令拦截智能重试**
- 修改 `diagnose.py` 添加 `handle_blocked_command()`
- 检测分号问题，自动切换 openssl
- 测试 outlookEmail 部署

### 📋 短期（1-2天）
**Phase 2: 多策略环境变量处理**
- 实现策略模式
- 支持 openssl、.env.example、默认值
- 测试多种项目类型

### 🎯 中期（1周内）
**Phase 3: 项目适应性分析**
- 深度分析项目特征
- 生成项目特定建议

### 🌟 长期（持续优化）
**Phase 4: 用户交互系统**
- 完善用户引导
- 优化交互体验

---

## 核心价值

### 🧠 真正的"智能"
- 不是硬编码规则，而是自适应决策
- 不是一刀切方案，而是因项目制宜
- 不是失败即停，而是智能重试和引导

### 🔧 运维智能体的定位
- **自动化优先**：能自动解决的绝不打扰用户
- **透明决策**：告诉用户"为什么这样做"
- **优雅降级**：无法自动解决时，提供清晰的手动步骤
- **持续学习**：记录常见问题，优化解决方案

### 🎯 用户体验
- **零配置部署**：大部分项目一键部署
- **明确的错误提示**：不是"部署失败"，而是"缺少 SECRET_KEY，已为您准备了3种解决方案"
- **可预测的行为**：用户知道智能体会做什么，不会做什么
