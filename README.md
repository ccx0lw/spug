<h1 align="center">Spug</h1>

<div align="center">

Spug是面向中小型企业设计的轻量级无Agent的自动化运维平台，整合了主机管理、主机批量执行、主机在线终端、应用发布部署、在线任务计划、配置中心、监控、报警等一系列功能。

</div>

- 官网地址：https://spug.cc
- 使用文档：https://spug.cc/docs/about-spug/
- 更新日志：https://spug.cc/docs/change-log/
- 常见问题：https://spug.cc/docs/faq/
- 推送助手：https://push.spug.cc

## 演示环境

演示地址：https://demo.spug.cc

## 🔐免费通配符SSL证书
免费通配符，付费证书价格亲民，性价比超高，低于市场其他平台价格，免费专家一对一配置服务，购买流程简单快速，且支持7天无理由退款和开具发票。提供一键下载和SSL过期通知配置，免费申请：[https://ssl.spug.cc](https://ssl.spug.cc)


## 🔥推送助手

推送助手是一个集成了电话、短信、邮件、飞书、钉钉、微信、企业微信等多通道的消息推送平台，可以3分钟实现Zabbix、Prometheus、夜莺等监控系统的电话短信报警，点击体验：[https://push.spug.cc](https://push.spug.cc)


## 特性

- **批量执行**: 主机命令在线批量执行
- **在线终端**: 主机支持浏览器在线终端登录
- **文件管理**: 主机文件在线上传下载
- **任务计划**: 灵活的在线任务计划
- **发布部署**: 支持自定义发布部署流程
- **配置中心**: 支持KV、文本、json等格式的配置
- **监控中心**: 支持站点、端口、进程、自定义等监控
- **报警中心**: 支持短信、邮件、钉钉、微信等报警方式
- **优雅美观**: 基于 Ant Design 的UI界面
- **开源免费**: 前后端代码完全开源


## 环境

* Python 3.6+
* Django 2.2
* Node 12.14
* React 16.11

## 安装

[官方文档](https://spug.cc/docs/install-docker)

更多使用帮助请参考： [使用文档](https://spug.cc/docs/host-manage/)


## 推荐项目
[Yearning — MYSQL 开源SQL语句审核平台](https://github.com/cookieY/Yearning)


## 预览

### 主机管理
![image](https://cdn.spug.cc/img/3.0/host.jpg)

#### 主机在线终端
![image](https://cdn.spug.cc/img/3.0/web-terminal.jpg)

#### 文件在线上传下载
![image](https://cdn.spug.cc/img/3.0/file-manager.jpg)

#### 主机批量执行
![image](https://cdn.spug.cc/img/3.0/host-exec.jpg)
![image](https://cdn.spug.cc/img/3.0/host-exec2.jpg)

#### 应用发布
![image](https://cdn.spug.cc/img/3.0/deploy.jpg)

#### 监控报警
![image](https://cdn.spug.cc/img/3.0/monitor.jpg)

#### 角色权限
![image](https://cdn.spug.cc/img/3.0/user-role.jpg)


## 赞助
<table>
  <thead>
    <tr>
      <th align="center" style="width: 115px;">
        <a href="https://www.ucloud.cn/site/active/kuaijie.html?invitation_code=C1xD0E5678FBA77">
          <img src="https://cdn.spug.cc/img/ucloud.png" width="115px"><br>
          <sub>UCloud</sub><br>
          <sub>5 元/月云主机</sub>
        </a>
      </th>
        <th align="center" style="width: 115px;">
        <a href="https://www.aliyun.com/minisite/goods?userCode=bkj6b9tn">
          <img src="https://cdn.spug.cc/img/aliyun-logo.png" width="115px"><br>
          <sub>阿里云</sub><br>
          <sub>2核心2G低至99元/年</sub>
        </a>
      </th>
      <th align="center" style="width: 125px;">
        <a href="http://www.magedu.com">
          <img src="https://cdn.spug.cc/img/magedu-logo.jpeg" width="115px"><br>
          <sub>马哥教育</sub><br>
          <sub>IT人高薪职业学院</sub>
        </a>
      </th>
    </tr>
  </thead>
</table>

## 开发者群
#### 关注Spug运维公众号加微信群、QQ群、获取最新产品动态
<div >
   <img src="https://cdn.spug.cc/img/spug-club.jpg" width = "300" height = "300" alt="spug-qq" align=center />
<div>
  
## License & Copyright
[AGPL-3.0](https://opensource.org/licenses/AGPL-3.0)


## 自定义开发
增加容器发布方式，支持docker/k8s发布。
优化界面、配置。给环境增加是否生产环境，如果是生产环境只能编译发布tag代码。
去掉服务配置中添加的参数 转为变量需要加前缀，服务配置中写的是什么key 直接就用什么key变量去取即可。
- **标签配置**: 可以自定义标签，给应用添加标签（eg: 前端、后端）
- **模板管理**: Dockerfile 、 k8s yaml
- **容器仓库**: docker容器仓库维护
- **容器镜像**: 镜像管理