/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useReducer} from 'react';
import { observer } from 'mobx-react';
import { Form, Button, Row, Col, Input, Card } from 'antd';
import { ACEditor } from 'components';
import { http, cleanCommand } from 'libs';
import Tips from './Tips';
import store from './store';
import HostSelector from 'pages/host/Selector';
import TemplateFileParameter from './TemplateFileParameter.js'
import { isEmpty } from 'lodash';

export default observer(function () {
  const reducerState = (state, action) => {
    switch (action.type) {
      case 'UPDATE_DOCKERFILE_PARAMS':
        const index = state.dockerfile_params?.findIndex(param => param.hasOwnProperty(action.variable));
        let newDockerfileParams = [...state.dockerfile_params];
        
        if (index !== -1) {
          newDockerfileParams[index] = {...newDockerfileParams[index], [action.variable]: action.value};
        } else {
          newDockerfileParams = [...newDockerfileParams, {[action.variable]: action.value}];
        }
        
        return {
          ...state,
          dockerfile_params: newDockerfileParams
        };
      default:
        return state;
    }
  };

  const [loading, setLoading] = useState(false)
  const [template, setTemplate] = useState({})
  const [parameters, setParameters] = useState([])
  const [state, dispatch] = useReducer(reducerState, { dockerfile_params: store.deploy.dockerfile_params||[] })

  const info = store.deploy

  useEffect(() => {
    setLoading(true);
    http.get('/api/config/file/template/?env_id='+store.deploy.env_id+'&type=dockerfile')
      .then(res => {
        setTemplate(res)
        setParameters(res.parameters || [])
        // 去掉不在parameters中的
        const parameterNames = new Set(res.parameters?.map(param => param.variable))
        store.deploy.dockerfile_params = store.deploy.dockerfile_params?.filter(param => {
          return Object.keys(param).some(key => parameterNames.has(key))
        }) || []
      })
      .finally(() => setLoading(false))
    initDefaultValue()
  }, [store.deploy.env_id])

  useEffect(() => {
    store.updateDeployDockerfileParmas(state.dockerfile_params);
  }, [state.dockerfile_params]);

  function handleNext() {
    store.page += 1
  }

  function initDefaultValue() {
    if (isEmpty(info['image_version'])) {
      info['image_version'] = "$SPUG_GIT_TAG"
    }
  }

  // 更新 `info['dockerfile_params']` 的函数
  const updateDockerfileParams = (variable, value) => {
    dispatch({ type: 'UPDATE_DOCKERFILE_PARAMS', variable, value });
  };

  return (
    <Form layout="vertical" style={{padding: '0 120px'}}>
      <Row gutter={24}>
        <Col span={14}>
          <Form.Item required label="镜像名称" tooltip="镜像名称">
            <Input value={info['image_name']} onChange={e => info['image_name'] = e.target.value} placeholder="请输入镜像名称"/>
          </Form.Item>
        </Col>
        <Col span={10}>
          <Form.Item required label="镜像版本" tooltip="镜像版本，支持变量配置 eg: $SPUG_GIT_TAG ; 设置变量会验证镜像不能重复">
            <Input value={info['image_version']} onChange={e => info['image_version'] = e.target.value} placeholder="请输入镜像版本"/>
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={24}>
        <Col span={14}>
          <Form.Item required label="编译机器" tooltip="该发布配置作用于哪些目标主机。（执行K8S/Docker命令的机器）">
            <HostSelector onlyOne={true} value={info['build_image_host_id']} onChange={id => info['build_image_host_id'] = id}/>
          </Form.Item>
        </Col>
        <Col span={10}>
          <Form.Item label="Dockerfile" tooltip="自动读取配置中心-模板文件（根据对应的环境自动读取）（会将Dockerfile文件写入到编译主机的发布目录）">
            {template.id > 0 ? (<span style={{color:"#11D16D"}}>存在模板文件(<a target="_blank" href='/config/file/template'>查看</a>)</span>) : (<span style={{color:"#f00"}}>不存在模板文件(<a target="_blank" href='/config/file/template'>去设置</a>)</span>)}
          </Form.Item>
        </Col>
      </Row>
      <Card size="small" title={"Dockerfile 动态参数"}>
        <TemplateFileParameter 
          parameters={parameters} 
          param_values={info['dockerfile_params']}
          onUpdate={(variable, value) => {updateDockerfileParams(variable, value)}}/>
      </Card>
      <Form.Item
        label="编译镜像"
        tooltip="在编译镜像的目标主机上运行，当前目录为目标主机上待发布的源代码目录，可执行任意自定义命令。（eg: 编译本地镜像）"
        extra={<span>{Tips}，此时还未进行文件变更，可进行一些发布前置操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_pre_image']}
          onChange={v => info['hook_pre_image'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item
        label="上传镜像"
        style={{marginTop: 12, marginBottom: 24}}
        tooltip="在编译镜像的目标主机上运行，当前目录为已发布的应用目录，可执行任意自定义命令。（eg: 上传镜像）"
        extra={<span>{Tips}，可以在发布后进行重启服务等操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_post_image']}
          onChange={v => info['hook_post_image'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item wrapperCol={{span: 14, offset: 6}}>
        <Button 
          type="primary"
          disabled={!(info.image_name && info.image_version && info.build_image_host_id && !loading)}
          onClick={handleNext}>下一步</Button>
        <Button style={{marginLeft: 20}} onClick={() => store.page -= 1}>上一步</Button>
      </Form.Item>
    </Form>
  )
})