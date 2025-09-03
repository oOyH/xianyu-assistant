# 🚀 GitHub Actions 工作流配置指南

本目录包含了闲鱼自动回复系统的完整CI/CD工作流配置。

## 📋 工作流概览

### 🐳 docker-build-and-push.yml
**主要的CI/CD流水线**，负责代码质量检查、多平台Docker镜像构建和发布。

**触发条件：**
- 推送到 `main`、`master`、`develop` 分支
- 创建以 `v` 开头的标签（如 `v1.0.0`）
- Pull Request 到主分支
- 手动触发

**功能特性：**
- ✅ Python代码质量检查（Black、isort、flake8、bandit）
- ✅ 多架构构建（AMD64、ARM64）
- ✅ Docker镜像安全扫描
- ✅ 自动推送到Docker Hub
- ✅ 基于Git标签的版本管理
- ✅ 自动创建GitHub Release

### 🔍 pr-check.yml
**Pull Request检查流水线**，确保代码质量和构建正常。

**触发条件：**
- Pull Request 创建、更新、重新打开

**检查项目：**
- 代码格式化检查
- 安全漏洞扫描
- Docker构建测试
- 文件变更分析
- 依赖安全检查

### 📦 dependency-update.yml
**依赖更新自动化流水线**，定期检查和更新Python依赖。

**触发条件：**
- 每周一早上8点自动执行
- 手动触发

**功能：**
- 检查过时的依赖包
- 安全漏洞扫描
- 自动创建更新PR
- 生成详细的更新报告

## 🔧 配置要求

### 必需的GitHub Secrets

在GitHub仓库的 `Settings > Secrets and variables > Actions` 中配置：

| Secret名称 | 描述 | 获取方式 |
|-----------|------|----------|
| `DOCKER_HUB_USERNAME` | Docker Hub用户名 | 您的Docker Hub账号 |
| `DOCKER_HUB_ACCESS_TOKEN` | Docker Hub访问令牌 | [创建访问令牌](https://hub.docker.com/settings/security) |

### Docker Hub访问令牌创建步骤

1. 登录 [Docker Hub](https://hub.docker.com/)
2. 点击右上角头像 → `Account Settings`
3. 选择 `Security` 标签页
4. 点击 `New Access Token`
5. 输入令牌名称（如：`github-actions`）
6. 选择权限：`Read, Write, Delete`
7. 点击 `Generate` 并复制生成的令牌

## 🏷️ 版本发布流程

### 自动发布（推荐）

1. **创建标签并推送：**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

2. **工作流自动执行：**
   - 构建多架构Docker镜像
   - 推送到Docker Hub
   - 创建GitHub Release
   - 生成发布说明

### 手动触发

1. 进入GitHub仓库的 `Actions` 标签页
2. 选择 `🐳 Docker Build and Push` 工作流
3. 点击 `Run workflow`
4. 选择分支并配置参数
5. 点击 `Run workflow` 开始执行

## 🐳 Docker镜像使用

### 拉取镜像

```bash
# 最新版本
docker pull your-username/xianyu-auto-reply:latest

# 特定版本
docker pull your-username/xianyu-auto-reply:v1.0.0

# 开发版本
docker pull your-username/xianyu-auto-reply:dev
```

### 支持的架构

- `linux/amd64` - Intel/AMD 64位处理器
- `linux/arm64` - ARM 64位处理器（如Apple M1、树莓派4等）

### 快速部署

```bash
# 下载docker-compose.yml
wget https://raw.githubusercontent.com/your-username/xianyu-auto-reply/main/docker-compose.yml

# 启动服务
docker-compose up -d
```

## 🔍 工作流状态监控

### 查看构建状态

在README.md中添加状态徽章：

```markdown
[![Docker Build](https://github.com/your-username/xianyu-auto-reply/actions/workflows/docker-build-and-push.yml/badge.svg)](https://github.com/your-username/xianyu-auto-reply/actions/workflows/docker-build-and-push.yml)
```

### 构建日志

1. 进入GitHub仓库的 `Actions` 标签页
2. 选择对应的工作流运行
3. 点击具体的作业查看详细日志

## 🛠️ 自定义配置

### 修改镜像名称

编辑 `.github/workflows/docker-build-and-push.yml`：

```yaml
env:
  REGISTRY: docker.io
  IMAGE_NAME: your-username/your-image-name  # 修改这里
```

### 添加新的触发分支

```yaml
on:
  push:
    branches:
      - main
      - master
      - develop
      - feature/*  # 添加新的分支模式
```

### 自定义构建参数

```yaml
- name: 🏗️ Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    build-args: |
      CUSTOM_ARG=value  # 添加自定义构建参数
```

## 🚨 故障排除

### 常见问题

1. **Docker Hub推送失败**
   - 检查 `DOCKER_HUB_USERNAME` 和 `DOCKER_HUB_ACCESS_TOKEN` 是否正确配置
   - 确认访问令牌有足够的权限

2. **多架构构建失败**
   - 检查Dockerfile是否支持多架构
   - 确认基础镜像支持目标架构

3. **代码质量检查失败**
   - 运行 `black .` 格式化代码
   - 运行 `isort .` 整理导入
   - 修复 flake8 报告的问题

### 调试技巧

1. **启用调试模式：**
   ```yaml
   env:
     ACTIONS_STEP_DEBUG: true
   ```

2. **查看详细日志：**
   在工作流中添加调试步骤：
   ```yaml
   - name: 🐛 Debug info
     run: |
       echo "Event: ${{ github.event_name }}"
       echo "Ref: ${{ github.ref }}"
       echo "SHA: ${{ github.sha }}"
   ```

## 📞 支持

如果遇到问题，请：

1. 查看 [GitHub Actions 文档](https://docs.github.com/en/actions)
2. 检查工作流运行日志
3. 在项目中创建 Issue 描述问题

---

**注意：** 请根据您的实际需求调整配置，确保所有敏感信息都通过GitHub Secrets管理。
