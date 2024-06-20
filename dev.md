## 二次开发

### 创建运行环境

```python
cd /data/spug/spug_api
python3 -m venv venv
# windows 使用 venv\Scripts\activate.bat
source venv/bin/activate
pip install -U pip setuptools
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
pip3 install mysqlclient
```

### 初始化数据库

```python
python manage.py updatedb
```

### 创建默认管理员账户

```python
python manage.py user add -u admin -p spug.cc -s -n 管理员

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

```python
cd /data/spug/spug_web
npm install --registry=https://registry.npm.taobao.org
```

### 启动前端

```python
npm start
```

### 访问测试
http://localhost:3000
用户名：admin  
密码：spug.cc



### 其它

```shell

# 安装v18
nvm install v18

# 设置环境变量，
export NODE_OPTIONS=--openssl-legacy-provider

# 设置node版本到v18
nvm use v18
```