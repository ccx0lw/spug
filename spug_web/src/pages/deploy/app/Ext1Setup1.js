/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Link } from 'react-router-dom';
import { Switch, Form, Input, Select, Button, Radio, Tag } from 'antd';
import Repo from './Repo';
import envStore from 'pages/config/environment/store';
import HostSelector from 'pages/host/Selector';
import store from './store';
import { isEmpty } from 'lodash';
import hostStore from 'pages/host/store';
import lds from 'lodash';

export default observer(function Ext1Setup1() {
  const [envs, setEnvs] = useState([]);
  const [visible, setVisible] = useState(false);

  function updateEnvs() {
    const ids = store.currentRecord['deploys'].map(x => x.env_id);
    setEnvs(ids.filter(x => x !== store.deploy.env_id))
  }

  useEffect(() => {
    hostStore.initial()
    if (store.currentRecord['deploys'] === undefined) {
      store.loadDeploys(store.app_id).then(updateEnvs)
    } else {
      updateEnvs()
    }
    _initDefaultValue()
  }, [])

  const info = store.deploy;
  let modePlaceholder;
  switch (info['rst_notify']['mode']) {
    case '0':
      modePlaceholder = '已关闭'
      break
    case '1':
      modePlaceholder = 'https://oapi.dingtalk.com/robot/send?access_token=xxx'
      break
    case '3':
      modePlaceholder = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'
      break
    case '4':
      modePlaceholder = 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx'
      break
    default:
      modePlaceholder = '请输入'
  }

  function _initDefaultValue() {
    if (isEmpty(info['dst_dir'])) {
      info['dst_dir'] = "/var/spug/apps/$SPUG_ENV_KEY/$SPUG_APP_KEY"
    }
    if (isEmpty(info['dst_repo'])) {
      info['dst_repo'] = "/var/spug/repos/$SPUG_ENV_KEY/$SPUG_APP_KEY"
    }
    if (info['versions'] === undefined) {
      info['versions'] = 1
    }
  }

  return (
    <Form labelCol={{span: 6}} wrapperCol={{span: 14}}>
      <Form.Item required label="发布环境" style={{marginBottom: 0}} tooltip="可以建立多个环境，实现同一应用在不同环境里配置不同的发布流程。">
        <Form.Item style={{display: 'inline-block', width: '80%'}}>
          <Select disabled={store.isReadOnly} value={info.env_id} 
            onChange={v => {
                info.env_id = v;
                // 查找并更新 env_name
                const selectedEnv = envStore.records.find(item => item.id === v);
                if (selectedEnv) {
                  info.env_name = selectedEnv.name;
                }
              }
            } 
            placeholder="请选择发布环境">
            {envStore.records.map(item => (
              <Select.Option disabled={envs.includes(item.id)} value={item.id} key={item.id}>{item.name}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item style={{display: 'inline-block', width: '20%', textAlign: 'right'}}>
          <Link disabled={store.isReadOnly} to="/config/environment">新建环境</Link>
        </Form.Item>
      </Form.Item>
      <Form.Item required label="目标主机" tooltip="该发布配置作用于哪些目标主机。">
        <HostSelector value={info.host_ids} onChange={ids => info.host_ids = ids}/>
        <span>
          {info.host_ids.slice(0, Math.min(3, info.host_ids.length)).map((id) => (
            <Tag color="#2db7f5" key={id} style={{ marginRight: 8 }}>
              {lds.get(hostStore.idMap, `${id}.name`)}[{lds.get(hostStore.idMap, `${id}.hostname`)}]
            </Tag>
          ))}
        </span>
        {info.host_ids.length > 3 ? (<span> ... 还有{info.host_ids.length-3}台</span>) : (<span></span>)}
      </Form.Item>
      <Form.Item required label="部署路径" tooltip="应用最终在主机上的部署路径，为了数据安全请确保该目录不存在，Spug 将会自动创建并接管该目录，可使用全局变量，例如：/www/$SPUG_APP_KEY">
        <Input value={info['dst_dir']} onChange={e => info['dst_dir'] = e.target.value} placeholder="请输入部署目标路径"/>
      </Form.Item>
      <Form.Item required label="存储路径" tooltip="此目录用于存储应用的历史版本，可使用全局变量，例如：/data/repos/$SPUG_APP_KEY">
        <Input value={info['dst_repo']} onChange={e => info['dst_repo'] = e.target.value} placeholder="请输入部署目标路径"/>
      </Form.Item>
      <Form.Item required label="版本数量" tooltip="早于指定数量的构建纪录及历史版本会被删除，以释放磁盘空间。">
        <Input value={info['versions']} onChange={e => info['versions'] = e.target.value} placeholder="请输入保存的版本数量"/>
      </Form.Item>
      <Form.Item required label="Git仓库地址" extra={<span className="btn" onClick={() => setVisible(true)}>私有仓库？</span>}>
        <Input disabled={store.isReadOnly} value={info['git_repo']} onChange={e => info['git_repo'] = e.target.value}
               placeholder="请输入Git仓库地址"/>
      </Form.Item>
      <Form.Item label="发布模式" tooltip="串行即发布时一台完成后再发布下一台，期间出现异常则终止发布。并行则每个主机相互独立发布同时进行。">
        <Radio.Group
          buttonStyle="solid"
          defaultValue={true}
          value={info.is_parallel}
          onChange={e => info.is_parallel = e.target.value}>
          <Radio.Button value={true}>并行</Radio.Button>
          <Radio.Button value={false}>串行</Radio.Button>
        </Radio.Group>
      </Form.Item>
      <Form.Item label="发布审核" tooltip="开启后发布申请需要审核（审核权限在系统管理/角色管理/功能权限中配置）通过后才能发布。">
        <Switch
          disabled={store.isReadOnly}
          checkedChildren="开启"
          unCheckedChildren="关闭"
          checked={info['is_audit']}
          onChange={v => info['is_audit'] = v}/>
      </Form.Item>
      <Form.Item label="消息通知" extra={<span>
        应用审核及发布成功或失败结果通知，
        <a target="_blank" rel="noopener noreferrer"
           href="https://spug.cc/docs/use-problem#use-dd">钉钉收不到通知？</a>
      </span>}>
        <Input
          addonBefore={(
            <Select
              disabled={store.isReadOnly}
              value={info['rst_notify']['mode']} style={{width: 100}}
              onChange={v => info['rst_notify']['mode'] = v}>
              <Select.Option value="0">关闭</Select.Option>
              <Select.Option value="1">钉钉</Select.Option>
              <Select.Option value="4">飞书</Select.Option>
              <Select.Option value="3">企业微信</Select.Option>
              <Select.Option value="2">Webhook</Select.Option>
            </Select>
          )}
          disabled={store.isReadOnly || info['rst_notify']['mode'] === '0'}
          value={info['rst_notify']['value']}
          onChange={e => info['rst_notify']['value'] = e.target.value}
          placeholder={modePlaceholder}/>
      </Form.Item>
      <Form.Item wrapperCol={{span: 14, offset: 6}}>
        <Button
          type="primary"
          disabled={!(info.env_id && info.git_repo && info.host_ids.length)}
          onClick={() => store.page += 1}>下一步</Button>
      </Form.Item>
      {visible && <Repo url={info['git_repo']} onOk={v => info['git_repo'] = v} onCancel={() => setVisible(false)}/>}
    </Form>
  )
})
