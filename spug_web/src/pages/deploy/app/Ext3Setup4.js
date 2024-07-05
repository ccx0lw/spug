/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useReducer} from 'react';
import { observer } from 'mobx-react';
import { Form, Button, message, Card } from 'antd';
import { ACEditor } from 'components';
import { http, cleanCommand } from 'libs';
import Tips from './Tips';
import store from './store';
import TemplateFileParameter from './TemplateFileParameter.js'

export default observer(function () {
  const reducerState = (state, action) => {
    switch (action.type) {
      case 'UPDATE_YAML_PARAMS':
        const index = state.yaml_params?.findIndex(param => param.hasOwnProperty(action.variable));
        let newYamlParams = [...state.yaml_params];
        
        if (index !== -1) {
          newYamlParams[index] = {...newYamlParams[index], [action.variable]: action.value};
        } else {
          newYamlParams = [...newYamlParams, {[action.variable]: action.value}];
        }
        
        return {
          ...state,
          yaml_params: newYamlParams
        };
      default:
        return state;
    }
  };


  const [loading, setLoading] = useState(false)
  const [template, setTemplate] = useState({})
  const [parameters, setParameters] = useState([])
  const [state, dispatch] = useReducer(reducerState, { yaml_params: store.deploy.yaml_params||[] })

  const info = store.deploy

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setLoading(true);
    http.get('/api/config/file/template/?env_id='+store.deploy.env_id+'&type=yaml')
      .then(res => {
        setTemplate(res)
        const pts = Array.isArray(res.parameters) ? res.parameters : [];
        setParameters(pts)
        const parameterNames = new Set(pts.map(param => param.variable));
        store.deploy.yaml_params = store.deploy.yaml_params?.filter(param => {
          return Object.keys(param).some(key => parameterNames.has(key))
        }) || [];
        pts.forEach(param => {
          if (!store.deploy.yaml_params.some(p => p.hasOwnProperty(param.variable)) && param.default != undefined) {
            store.deploy.yaml_params.push({[param.variable]: param.default});
          }
        });
      })
      .finally(() => setLoading(false))
  }, [store.deploy.env_id])

  useEffect(() => {
    store.updateDeployYamlParmas(state.yaml_params);
  }, [state.yaml_params]);

  function handleSubmit() {
    const {dst_dir, dst_repo} = store.deploy;
    const t_dst_dir = dst_dir?.replace(/\/*$/, '/');
    const t_dst_repo = dst_repo?.replace(/\/*$/, '/');
    if (t_dst_repo?.includes(t_dst_dir)) {
      return message.error('存储路径不能位于部署路径内')
    }
    setLoading(true);
    info['app_id'] = store.app_id;
    info['extend'] = '3';
    http.post('/api/app/deploy/', info)
      .then(() => {
        message.success('保存成功');
        store.loadDeploys(store.app_id);
        store.ext3Visible = false
      }, () => setLoading(false))
  }

  // 更新 `info['yaml_params']` 的函数
  const updateYamlParams = (variable, value) => {
    dispatch({ type: 'UPDATE_YAML_PARAMS', variable, value });
  };

  return (
    <Form layout="vertical" style={{padding: '0 120px'}}>
      <Card size="small" title={template.id > 0 ? (<span style={{color:"#11D16D"}}>发布模板yaml参数配置(<a target="_blank" href='/config/file/template'>查看</a>)</span>) : (<span style={{color:"#f00"}}>当前环境不存在yaml模板文件(<a target="_blank" href='/config/file/template'>去设置</a>)</span>)}>
        <TemplateFileParameter 
          parameters={parameters}
          param_values={info['yaml_params']}
          onUpdate={updateYamlParams}/>
      </Card>
      <Form.Item
        label="应用发布前执行"
        tooltip="在发布的目标主机上运行，当前目录为目标主机上待发布的源代码目录，可执行任意自定义命令。（如果配置了yaml模板，则需要自己用envsubst替换模板文件生成新的文件）"
        extra={<span>{Tips}，此时还未进行文件变更，可进行一些发布前置操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_pre_host']}
          onChange={v => info['hook_pre_host'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item
        label="应用发布后执行"
        style={{marginTop: 12, marginBottom: 24}}
        tooltip="在发布的目标主机上运行，当前目录为已发布的应用目录，可执行任意自定义命令。"
        extra={<span>{Tips}，可以在发布后进行重启服务等操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_post_host']}
          onChange={v => info['hook_post_host'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item
        label="重启应用的脚本"
        style={{marginTop: 12, marginBottom: 24}}
        tooltip="重启应用的脚本（不会上传文件，但是可以使用除代码相关以外的环境变量）"
        extra={<span>{Tips}，可以在发布后进行重启服务等操作。</span>}>
        <ACEditor
          readOnly={store.isReadOnly}
          mode="sh"
          theme="tomorrow"
          width="100%"
          height="150px"
          placeholder="输入要执行的命令"
          value={info['hook_restart_host']}
          onChange={v => info['hook_restart_host'] = cleanCommand(v)}
          style={{border: '1px solid #e8e8e8'}}/>
      </Form.Item>
      <Form.Item wrapperCol={{span: 14, offset: 6}}>
        <Button disabled={store.isReadOnly} loading={loading} type="primary" onClick={handleSubmit}>提交</Button>
        <Button style={{marginLeft: 20}} onClick={() => store.page -= 1}>上一步</Button>
      </Form.Item>
    </Form>
  )
})