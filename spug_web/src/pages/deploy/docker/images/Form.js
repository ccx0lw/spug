/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { LoadingOutlined, SyncOutlined } from '@ant-design/icons';
import { Modal, Form, Input, Select, Button, message, Tag } from 'antd';
import http from 'libs/http';
import store from './store';
import lds from 'lodash';
import tagStore from 'pages/config/tag/store';
import moment from 'moment';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [git_type, setGitType] = useState();
  const [extra, setExtra] = useState([]);
  const [extra1, setExtra1] = useState();
  const [extra2, setExtra2] = useState();
  const [versions, setVersions] = useState({});
  const [appTags, setAppTags] = useState([]);
  const [repositories, setRepositories] = useState([]);

  useEffect(() => {
    fetchVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    setAppTags(tagStore.records)
  }, [])

  function _setDefault(type, new_extra, new_versions, new_repositories) {
    const now_extra = new_extra || extra;
    const now_versions = new_versions || versions;
    const now_repositories = new_repositories || repositories;
    const {branches, tags} = now_versions;
    if (type === 'branch') {
      let [branch, commit] = [now_extra[1], null];
      if (branches[branch]) {
        commit = lds.get(branches[branch], '0.id')
      } else {
        branch = lds.get(Object.keys(branches), 0)
        commit = lds.get(branches, [branch, 0, 'id'])
      }
      setExtra1(branch)
      setExtra2(commit)
    } else if (type === 'tag') {
      setExtra1(lds.get(Object.keys(tags), 0))
      setExtra2(null)
    } else {
      setExtra1(lds.get(now_repositories, '0.id'))
      setExtra2(null)
    }
  }

  function _initial(versions, repositories) {
    if (store.deploy.env_prod) {
      return _setDefault('tags', null, null, null)
    }

    const {branches, tags} = versions;
    if (branches && tags) {
      for (let item of store.records) {
        if (item.deploy_id === store.deploy.id) {
          const type = item.extra[0];
          setExtra(item.extra);
          setGitType(type);
          return _setDefault(type, item.extra, versions, repositories);
        }
      }
      setGitType('branch');
      const branch = lds.get(Object.keys(branches), 0);
      const commit = lds.get(branches, `${branch}.0.id`);
      setExtra1(branch);
      setExtra2(commit)
    }
  }

  function fetchVersions() {
    setFetching(true);
    const deploy_id = store.deploy.id;
    const p1 = http.get(`/api/app/deploy/${deploy_id}/versions/`, {timeout: 300000});
    const p2 = http.get('/api/repository/', {params: {deploy_id}});
    Promise.all([p1, p2])
      .then(([res1, res2]) => {
        _initial(res1, res2);
        setVersions(res1);
        var tmp = res2;
        if (store.deploy.env_prod) {
          tmp = res2.filter(item => item?.extra?.length > 0 && item?.extra[0] == 'tag');
        };
        setRepositories(tmp);
      })
      .finally(() => setFetching(false));
  }

  function switchType(v) {
    setGitType(v);
    _setDefault(v);
  }

  function switchExtra1(v) {
    setExtra1(v)
    if (git_type === 'branch') {
      setExtra2(lds.get(versions.branches[v], '0.id'))
    }
  }

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['deploy_id'] = store.deploy.id;
    formData['extra'] = [git_type, extra1, extra2];
    http.post('/api/docker_image/', formData)
      .then(res => {
        message.success('操作成功');
        store.formVisible = false;
        store.showConsole(res)
      }, () => setLoading(false))
  }

  const {branches, tags} = versions;
  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={
        <div>
          {store.deploy.env_name ? <Tag color="#108ee9">{store.deploy.env_name}</Tag> : null}
          <span>新建镜像编译【<b>{store.deploy.app_name}</b>】</span>
          {store.deploy.app_rel_tags?.length > 0 && Array.isArray(appTags) ? store.deploy.app_rel_tags.map(tid => (
            appTags.find(item => item.id === tid) ? <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{appTags.find(item => item.id === tid).name}</Tag> : null
          )) : null}
          {store.deploy.env_prod ? <Tag color="#f50">生产环境</Tag> : null}
        </div>
      }
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={store.record} labelCol={{span: 5}} wrapperCol={{span: 17}}>
        {/* <Form.Item required name="version" label="构建版本">
          <Input placeholder="请输入构建版本"/>
        </Form.Item> */}
        <Form.Item required label="选择分支/标签/版本" style={{marginBottom: 12}} extra={<span>
            根据网络情况，首次刷新可能会很慢，请耐心等待。
            <a target="_blank" rel="noopener noreferrer"
               href="https://spug.cc/docs/use-problem#clone">clone 失败？</a>
          </span>}>
          <Form.Item style={{display: 'inline-block', marginBottom: 0, width: '450px'}}>
            <Input.Group compact>
              <Select value={git_type} onChange={switchType} style={{width: 100}}>
                <Select.Option value="branch">Branch</Select.Option>
                <Select.Option value="tag">Tag</Select.Option>
                <Select.Option value="repository">构建仓库</Select.Option>
              </Select>
              <Select
                showSearch
                style={{width: 350}}
                value={extra1}
                placeholder="请稍等"
                onChange={switchExtra1}
                filterOption={(input, option) => option.props.children.toLowerCase().indexOf(input.toLowerCase()) >= 0}>
                {git_type === 'branch' ? (
                  Object.keys(branches || {}).map(b => <Select.Option key={b} value={b}>{b}</Select.Option>)
                ) : git_type === 'tag' ? (
                  Object.entries(tags || {}).map(([tag, info]) => (
                    <Select.Option key={tag} value={tag}>
                      <div style={{display: 'flex', justifyContent: 'space-between'}}>
                        <span style={{
                          width: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>{`${tag} ${info.author} ${info.message}`}</span>
                        <span style={{color: '#999', fontSize: 12}}>{info['date']} </span>
                      </div>
                    </Select.Option>
                  ))
                ) : (
                  repositories.map(item => (
                    <Select.Option key={item.id} value={item.id} content={item.version}>
                      <div style={{display: 'flex', justifyContent: 'space-between'}}>
                        <span>{item.version}</span>
                        <span style={{color: '#999', fontSize: 12}}>构建于 {moment(item.created_at).fromNow()}</span>
                      </div>
                    </Select.Option>
                  ))
                )}
              </Select>
            </Input.Group>
          </Form.Item>
          <Form.Item style={{display: 'inline-block', width: 82, textAlign: 'center', marginBottom: 0}}>
            {fetching ? <LoadingOutlined style={{fontSize: 18, color: '#1890ff'}}/> :
              <Button type="link" icon={<SyncOutlined/>} disabled={fetching} onClick={fetchVersions}>刷新</Button>
            }
          </Form.Item>
        </Form.Item>
        {git_type === 'branch' && (
          <Form.Item required label="选择Commit ID">
            <Select value={extra2} placeholder="请选择" onChange={v => setExtra2(v)}>
              {extra1 && branches ? branches[extra1].map(item => (
                <Select.Option key={item.id}>
                  <div style={{display: 'flex', justifyContent: 'space-between'}}>
                    <span style={{
                      width: 400,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>{item.id.substr(0, 6)} {item['author']} {item['message']}</span>
                    <span style={{color: '#999', fontSize: 12}}>{item['date']} </span>
                  </div>
                </Select.Option>
              )) : null}
            </Select>
          </Form.Item>
        )}
        <Form.Item name="remarks" label="备注信息">
          <Input placeholder="请输入备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})