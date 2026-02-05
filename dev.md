## 二次开发

```
# ubuntu 24.04
docker run -itd --network host --name spug -v /home/xxx/workspace/workspace-python/spug:/root/spug:rw ubuntu:22.04
```

```
# 容器 ubuntu 22.04
apt install -y git libmariadbd-dev python3-dev python3-venv libsasl2-dev libldap2-dev redis-server gcc libssl-dev curl

curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

```

### 创建运行环境

```python
cd spug_api
python3 -m venv venv
# windows 使用 venv\Scripts\activate.bat
source venv/bin/activate
pip install -U pip setuptools
pip install -r requirements.txt  #-i https://pypi.tuna.tsinghua.edu.cn/simple/
pip install mysqlclient==2.1.0
```

### 初始化数据库

```python
python manage.py updatedb
```

### 创建默认管理员账户

```python
python manage.py user add -u admin -p 123456 -s -n 管理员

# -u 用户名
# -p 密码
# -s 超级管理员
# -n 用户昵称
```

### 启动 api 开发环境服务

```python
python manage.py runserver
```

### 安装前端依赖
可以把 npm 用 yarn 或 cnpm 代替。

```bash
cd spug_web
npm install #--registry=https://registry.npm.taobao.org
```

### 启动前端

```bash
npm start
```
#### docker 容器中 开发环境启动
‵‵‵bash
node node_modules/react-app-rewired/bin/index.js start
```

### 访问测试
http://localhost:3000
用户名：admin  
密码：123456



### 其它

```shell
# v12.18.1
nvm install 12.18.1

nvm use 12.18.1

# # 安装v18
# nvm install v18

# # 设置环境变量，
# export NODE_OPTIONS=--openssl-legacy-provider

# # 设置node版本到v18
# nvm use v18
```